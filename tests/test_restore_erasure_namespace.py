"""Standalone SOURCE regression; no provider/package import, SDK or restore.

Run directly with stdlib Python (NOT pytest beneath the provider package):
  python -I -B -S tests/test_restore_erasure_namespace.py --scratch <owned-empty-dir>
Optional --source selects an unchanged historical full __init__.py; --case selects
one main unittest ID. The loader executes ONLY four exact top-level definitions
from actual full-source bytes, with their original AST locations/future flags.
ZIP fixtures are real in-memory ZipFiles. No external evidence peer is required.
"""
from __future__ import annotations

import argparse
import ast
import builtins
from contextlib import contextmanager
import dis
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import types
from typing import List
import unittest
import zipfile

FUNCTIONS = ("safe_join", "zip_member_safe", "zip_member_regular", "validate_restore_archive")
LIMITS = {"MEMORY_WIKI_RESTORE_MAX_FILES": "20000",
          "MEMORY_WIKI_RESTORE_MAX_BYTES": str(2 * 1024**3),
          "MEMORY_WIKI_RESTORE_MAX_MEMBER_BYTES": str(1024**3),
          "MEMORY_WIKI_RESTORE_MAX_RATIO": "200"}


def selected_ast(raw):
    tree = ast.parse(raw)
    future = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
    nodes = []
    for name in FUNCTIONS:
        matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
        if len(matches) != 1 or matches[0].decorator_list:
            raise ValueError("unique_undecorated_top_level_function_required:" + name)
        nodes.append(matches[0])
    return ast.Module(body=future + nodes, type_ignores=[]), nodes


def dependency_names(code):
    names = {i.argval for i in dis.get_instructions(code) if i.opname in ("LOAD_GLOBAL", "LOAD_NAME")}
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            names |= dependency_names(value)
    return names


def load_functions(raw, source):
    selected, nodes = selected_ast(raw)
    namespace = {"__name__": "restore_namespace_source_functions", "__builtins__": builtins.__dict__,
                 "Path": Path, "List": List, "os": os, "stat": stat, "zipfile": zipfile, "re": re}
    code = compile(selected, str(source), "exec", dont_inherit=True)
    # Definitions and their annotations may depend only on the actual stdlib
    # globals above, sibling selected functions, and builtins; never SDK stubs.
    missing = dependency_names(code) - set(namespace) - set(FUNCTIONS) - set(dir(builtins)) - {"annotations"}
    if missing:
        raise ValueError("unbound_source_dependencies:" + ",".join(sorted(missing)))
    exec(code, namespace)
    bindings = [{"qualified_AST": n.name, "node": type(n).__name__, "lines": [n.lineno, n.end_lineno],
                 "ast_sha256": hashlib.sha256(ast.dump(n, include_attributes=False).encode()).hexdigest()}
                for n in nodes]
    return namespace, bindings


@contextmanager
def limits(**overrides):
    before = {key: os.environ.get(key) for key in LIMITS}
    values = dict(LIMITS)
    for name, value in overrides.items():
        values["MEMORY_WIKI_RESTORE_MAX_" + name] = str(value)
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def archive(names, payload=b"ordinary synthetic data", *, mode=stat.S_IFREG, encrypted=False,
            compression=zipfile.ZIP_STORED):
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w", compression=compression) as writer:
            for name in names:
                info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (mode | 0o600) << 16
                info.compress_type = compression
                writer.writestr(info, payload)
        raw = bytearray(buffer.getvalue())
        if encrypted:
            # Stdlib cannot produce encrypted data. Set actual local+central ZIP
            # metadata encryption bits; validator never reads the member data.
            # One stored tiny member, no signature collision in its payload.
            if len(names) != 1 or raw.count(b"PK\x01\x02") != 1:
                raise ValueError("one_encryption_metadata_fixture_required")
            for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
                pos = raw.index(signature) + offset
                flags = struct.unpack_from("<H", raw, pos)[0]
                struct.pack_into("<H", raw, pos, flags | 1)
        with io.BytesIO(raw) as reader, zipfile.ZipFile(reader, "r") as zf:
            yield zf


def metadata(zf):
    return [(i.filename, i.orig_filename, i.external_attr, i.flag_bits, i.file_size, i.compress_size)
            for i in zf.infolist()]


class RestoreNamespaceTests(unittest.TestCase):
    def setUp(self):
        self.root = self.scratch / self._testMethodName
        self.root.mkdir(parents=True, exist_ok=False)
        self.validate = self.functions["validate_restore_archive"]

    def witness(self, value):
        raw = (json.dumps(value, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")
        with (self.root / "witness.json").open("xb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())

    def refuse(self, names, reason, *, payload=b"ordinary synthetic data", options=None, **zip_options):
        for name in names:
            with archive([name], payload, **zip_options) as zf, limits(**(options or {})):
                before = metadata(zf)
                with self.assertRaisesRegex(ValueError, reason, msg=name):
                    self.validate(zf)
                self.assertEqual(metadata(zf), before, "rejection must not rewrite metadata")

    def allow(self, names, *, payload=b"ordinary synthetic data", options=None, **zip_options):
        with archive(names, payload, **zip_options) as zf, limits(**(options or {})):
            before = metadata(zf)
            result = self.validate(zf)
            expected = [i for i in zf.infolist() if not i.is_dir()]
            self.assertEqual(len(result), len(expected))
            self.assertTrue(all(a is b for a, b in zip(result, expected)))
            self.assertEqual([i.filename for i in result], [i.filename for i in expected])
            self.assertEqual(metadata(zf), before, "admission must preserve raw ZipInfo names")

    def test_dot_alias_rejected(self):
        alias = "./privacy-erasure/key.bin"
        with archive([alias]) as zf, limits():
            before = metadata(zf)
            admitted, error = None, None
            try:
                admitted = self.validate(zf)
            except ValueError as exc:
                error = str(exc)
            # Only the vulnerable baseline plans a destination. This is a
            # read-only path calculation; neither target nor restore is run.
            destination = (self.functions["safe_join"](self.root, admitted[0].filename)
                           if admitted is not None else None)
            self.witness({"raw_alias": alias, "validator_accepted": admitted is not None,
                          "returned_raw_filenames": [i.filename for i in admitted] if admitted is not None else None,
                          "zip_member_safe": self.functions["zip_member_safe"](alias),
                          "planned_destination": str(destination) if destination is not None else None,
                          "protected_canonical_destination": str(self.root / "privacy-erasure" / "key.bin"),
                          "addresses_protected_canonical": destination == self.root / "privacy-erasure" / "key.bin",
                          "rejection": error, "actual_restore_executed": False,
                          "metadata_unchanged": metadata(zf) == before})
            self.assertIsNotNone(error, "reserved_dot_alias_was_admitted")
            self.assertIsNone(admitted)
            self.assertEqual(metadata(zf), before)

    def test_canonical_erasure_root_key_log_rejected(self):
        self.refuse(["privacy-erasure", "privacy-erasure/key.bin", "privacy-erasure/intents.jsonl",
                     "privacy-erasure/ordinary.txt"], "host privacy erasure ledger")

    def test_case_backslash_and_dot_aliases_rejected(self):
        self.refuse(["PRIVACY-ERASURE/KEY.BIN", "privacy-erasure\\key.bin", ".\\privacy-erasure\\key.bin",
                     "././privacy-erasure/intents.jsonl", "privacy-erasure/./key.bin",
                     "pr\u0131vacy-erasure/key.bin", "privacy-era\u017fure/key.bin"],
                    "unsafe zip member|host privacy erasure ledger")

    def test_bootstrap_init_lock_and_stage_namespaces_rejected(self):
        self.refuse(["privacy-erasure.init.lock", "privacy-erasure.init.lock/child", "PRIVACY-ERASURE.INIT.LOCK",
                     ".privacy-erasure-stage-", ".privacy-erasure-stage-owned", ".privacy-erasure-stage-owned/key.bin",
                     ".PRIVACY-ERASURE-STAGE-X/key.bin", "./privacy-erasure.init.lock",
                     ".\\.privacy-erasure-stage-x\\key.bin"], "unsafe zip member|host privacy erasure ledger")

    def test_win32_dot_space_and_ambiguous_components_rejected(self):
        self.refuse(["privacy-erasure./key.bin", "privacy-erasure /key.bin", "privacy-erasure. /key.bin",
                     "privacy-erasure.init.lock.", ".privacy-erasure-stage-x ", "privacy-erasure::$DATA",
                     "privacy-erasure:key.bin", "pages/../privacy-erasure/key.bin", "pages/.. /item",
                     "pages/./item", "./pages/item", "pages//item", "pages\\.\\item", "pages/item.",
                     "pages/item ", "pages/item\t", "pages/a?b", "pages/a*b", "pages/a<b", "pages/a>b",
                     "pages/a\"b", "pages/a|b", "NUL", "pages/con.txt", "pages/COM1", "pages/LPT\u00b2.txt",
                     "PRIVAC~1/key.bin", "PR1234~2/key.bin", "pages/ERASUR~1.BIN"], "unsafe zip member")

    def test_existing_escape_and_empty_path_guard(self):
        self.refuse(["../outside", "pages/../../outside", "/outside", "C:/outside", "C:relative",
                     "\\\\server\\share\\outside"], "unsafe zip member")
        self.assertFalse(self.functions["zip_member_safe"](""))

    def test_ordinary_pages_journal_and_raw_zipinfo_preserved(self):
        self.allow(["pages/a.md", "journal/events.jsonl", "dashboards/home.md", "snapshots/a.json",
                    "pages\\windows.md", "Pages/Mixed Case.md", "pages/заметка.md"])

    def test_benign_root_lookalikes_allowed(self):
        self.allow(["privacy-erasure.txt", "privacy-erasure-old/key.bin", "privacy-erasure.init.locked",
                    ".privacy-erasure-stage", ".privacy-erasure-stageish/key.bin", "xprivacy-erasure/key.bin",
                    "notes~draft.md", "notes~2024.md", "privacy-erasure~1.md"])

    def test_nested_ordinary_erasure_documentation_allowed(self):
        self.allow(["docs/privacy-erasure/key.bin", "docs/privacy-erasure/intents.jsonl",
                    "docs/privacy-erasure.init.lock", "docs/.privacy-erasure-stage-example/readme.md"])

    def test_directory_entries_remain_ignored(self):
        self.allow(["pages/", "pages/a.md"])

    def test_special_file_modes_rejected(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK):
            self.refuse(["pages/special"], "unsafe zip member", mode=mode)

    def test_untyped_regular_metadata_allowed(self):
        self.allow(["pages/untyped"], mode=0)

    def test_encrypted_metadata_rejected(self):
        self.refuse(["pages/encrypted"], "encrypted zip member is unsupported", encrypted=True)

    def test_member_size_limit_rejected(self):
        self.refuse(["pages/large"], "backup member exceeds size limit", payload=b"m" * 1000001,
                    options={"MEMBER_BYTES": 1000000, "BYTES": 3000000})

    def test_total_expansion_limit_rejected(self):
        with archive(["pages/one", "pages/two"], b"t" * 600001) as zf, limits(BYTES=1000000, MEMBER_BYTES=2000000):
            with self.assertRaisesRegex(ValueError, "backup expands beyond configured limit"):
                self.validate(zf)

    def test_file_count_limit_rejected(self):
        with archive(["pages/one", "pages/two"]) as zf, limits(FILES=1):
            with self.assertRaisesRegex(ValueError, "backup contains too many files"):
                self.validate(zf)

    def test_large_compression_ratio_rejected(self):
        self.refuse(["pages/compressed"], "suspicious compression ratio", payload=b"r" * 1048577,
                    compression=zipfile.ZIP_DEFLATED, options={"MEMBER_BYTES": 3000000, "BYTES": 4000000, "RATIO": 5})

    def test_healthy_limit_boundaries_allowed(self):
        self.allow(["pages/exact"], payload=b"b" * 1000000,
                   options={"FILES": 1, "MEMBER_BYTES": 1000000, "BYTES": 1000000})
        self.allow(["pages/small_compressed"], payload=b"r" * 1048576, compression=zipfile.ZIP_DEFLATED,
                   options={"MEMBER_BYTES": 2000000, "BYTES": 3000000, "RATIO": 5})

    def test_safe_join_containment_and_ordinary_positive(self):
        self.assertEqual(self.functions["safe_join"](self.root, "pages", "a.md"), self.root / "pages" / "a.md")
        with self.assertRaisesRegex(ValueError, "path escapes memory-wiki root"):
            self.functions["safe_join"](self.root, "..", "outside")


def make_suite(raw, source, scratch, cases=None):
    functions, bindings = load_functions(raw, source)
    ids = sorted(n for n in RestoreNamespaceTests.__dict__ if n.startswith("test_"))
    selected = ids if cases is None else list(cases)
    if not selected or len(set(selected)) != len(selected) or not set(selected).issubset(ids):
        raise ValueError("invalid_case_roster")
    suite = unittest.TestSuite()
    for name in selected:
        case = RestoreNamespaceTests(name)
        case.functions, case.bindings, case.scratch = functions, bindings, Path(scratch)
        suite.addTest(case)
    return suite, bindings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).absolute().parents[1] / "__init__.py")
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    # Caller supplies a new owned directory. Never default to a real home/temp.
    args.scratch.mkdir(parents=True, exist_ok=False)
    suite, _ = make_suite(args.source.read_bytes(), args.source, args.scratch, args.case)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
