"""Bound owned post-job artifacts by metadata only, before upload/parse.

This is one owned, quiescent snapshot: not an atomic concurrent-writer fence,
not a producer disk/RSS limit, and never native/source/SDK acceptance proof.
"""
import argparse
import json
import os
from pathlib import Path, PureWindowsPath
import stat

DEFAULT_LIMITS = {"lane_total": 24000000, "json_member": 4000000,
    "junit_member": 8000000, "log_member": 8000000,
    "aggregate_total": 4000000, "decision": 4096}
NATIVE_NAMES = ("receipt.json", "execution.json", "source-inventory.json",
    "native-origins.json", "bindings.json", "launches.json", "binding-coverage.json",
    "phases.json", "junit.xml", "pytest.log", "pytest-detail.log", "recovery-observations.json")
AGGREGATE_NAMES = ("matrix-coverage.json", "receipt.json")
# The unchanged aggregate also writes this local, non-uploaded product.
AGGREGATE_LOCAL_EXTRA = ("source-inventory.json",)
GROUPS = tuple(f"native-{os_name}-{version}-{stage}"
    for os_name in ("ubuntu-latest", "windows-latest")
    for version in ("3.11", "3.12", "3.13", "3.14")
    for stage in ("full", "recovery"))
REFUSAL_NAME = "ci-output-admission.json"
REPARSE = 0x400


class AdmissionError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & REPARSE)


def _path(path, create_parents=False):
    path = Path(path)
    if ".." in path.parts or ".." in PureWindowsPath(str(path)).parts:
        raise AdmissionError("unsafe_path")
    path = path.absolute()  # Never resolve/follow a link to legalize it.
    for ancestor in reversed(path.parents):
        try:
            info = os.lstat(ancestor)
        except FileNotFoundError:
            if not create_parents:
                raise AdmissionError("missing_root") from None
            os.mkdir(ancestor)
            info = os.lstat(ancestor)
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            raise AdmissionError("unsafe_path")
    return path


def _directory(path):
    path = _path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        raise AdmissionError("missing_root") from None
    if _linked(info) or not stat.S_ISDIR(info.st_mode):
        raise AdmissionError("unsafe_path")
    return path


def _entries(root, maximum):
    root = _directory(root)
    entries = []
    with os.scandir(root) as stream:
        for entry in stream:
            entries.append(entry)
            if len(entries) > maximum:
                raise AdmissionError("too_many_entries")
    if len({entry.name.casefold() for entry in entries}) != len(entries):
        raise AdmissionError("duplicate_or_linked_member")
    return sorted(entries, key=lambda entry: entry.name)


def _caps(limits):
    caps = dict(DEFAULT_LIMITS)
    if limits is not None:
        if not isinstance(limits, dict) or set(limits) - set(caps):
            raise AdmissionError("invalid_limits")
        for key, value in limits.items():
            # A test can lower caps; production CLI has no cap-override input.
            if type(value) is not int or not 0 < value <= caps[key]:
                raise AdmissionError("invalid_limits")
        caps.update(limits)
    return caps


def _members(root, allowed, required, total_cap, caps, identities, receiver=False):
    entries = _entries(root, len(allowed) + (1 if receiver else 0))
    names = {entry.name for entry in entries}
    if receiver and REFUSAL_NAME in names:
        raise AdmissionError("producer_refused")  # No JSON open, even for a tiny refusal.
    if names - set(allowed):
        raise AdmissionError("unknown_member")
    if not set(required) <= names:
        raise AdmissionError("missing_required")
    total = 0
    for entry in entries:
        # Windows DirEntry.stat() caches zero inode/nlink; lstat supplies
        # actual no-follow identity/link metadata without reading payload.
        info = os.lstat(entry.path)
        if _linked(info) or not stat.S_ISREG(info.st_mode):
            raise AdmissionError("nonregular_member")
        identity = (info.st_dev, info.st_ino)
        if info.st_nlink != 1 or identity in identities:
            raise AdmissionError("duplicate_or_linked_member")
        identities.add(identity)
        limit = caps["junit_member" if entry.name == "junit.xml" else
            "log_member" if entry.name.endswith(".log") else "json_member"]
        if info.st_size < 0 or info.st_size > limit:
            raise AdmissionError("member_too_large")
        total += info.st_size
        if total > total_cap:
            raise AdmissionError("total_too_large")
    return {"files": len(entries), "bytes": total}


def admit(root, mode, limits=None):
    """Stat the complete allowlisted product; never read/parse any payload."""
    caps, identities = _caps(limits), set()
    if mode == "native":
        return _members(root, NATIVE_NAMES, ("receipt.json", "source-inventory.json"),
            caps["lane_total"], caps, identities)
    if mode == "aggregate":
        return _members(root, AGGREGATE_NAMES + AGGREGATE_LOCAL_EXTRA, AGGREGATE_NAMES,
            caps["aggregate_total"], caps, identities)
    if mode != "downloaded":
        raise AdmissionError("invalid_mode")
    entries = _entries(root, len(GROUPS))
    if {entry.name for entry in entries} != set(GROUPS):
        raise AdmissionError("group_set_mismatch")
    total, count = 0, 0
    required = ("receipt.json", "source-inventory.json", "launches.json", "bindings.json", "native-origins.json")
    for entry in entries:
        product = _members(entry.path, NATIVE_NAMES, required, caps["lane_total"],
            caps, identities, receiver=True)
        total += product["bytes"]
        count += product["files"]
        if total > len(GROUPS) * caps["lane_total"]:
            raise AdmissionError("total_too_large")
    return {"groups": len(entries), "files": count, "bytes": total}


def _write_new_refusal(path, mode, code):
    if Path(path).name != REFUSAL_NAME:
        raise AdmissionError("unsafe_path")
    raw = (json.dumps({"schema": "ci-output-admission-v1", "scope": mode, "status": "refused",
        "code": code, "capacity_admitted": False, "native_proof": False,
        "detailed_evidence_withheld": True, "limits_bytes": DEFAULT_LIMITS,
        "boundary": "owned post-job snapshot; not producer growth/RSS or concurrent-writer proof"},
        sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > DEFAULT_LIMITS["decision"]:
        raise AdmissionError("decision_too_large")
    path = _path(path, create_parents=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
    try:
        if os.write(descriptor, raw) != len(raw):
            raise OSError("Short decision write")
    finally:
        os.close(descriptor)


def _write_outputs(path, admitted, refusal):
    path = _path(path)
    info = os.lstat(path)
    if _linked(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AdmissionError("unsafe_path")
    raw = ("admitted=" + ("true" if admitted else "false") + "\nrefusal=" +
        ("true" if refusal else "false") + "\n").encode("ascii")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    try:
        opened = os.fstat(descriptor)
        if _linked(opened) or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise AdmissionError("unsafe_path")
        if os.write(descriptor, raw) != len(raw):
            raise OSError("Short step-output write")
    finally:
        os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("native", "aggregate", "downloaded"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--decision", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    admitted, refusal, code, summary = False, False, "capacity_only", {}
    try:
        summary = admit(args.root, args.mode)
        admitted = True
    except AdmissionError as exc:
        code = exc.code
    except OSError:
        code = "filesystem_error"
    if not admitted and args.decision is not None:
        try:
            _write_new_refusal(args.decision, args.mode, code)
            refusal = True
        except (OSError, AdmissionError):
            code = "refusal_unavailable"  # No overwrite/deletion of a previous refusal.
    if args.github_output is not None:
        try:
            _write_outputs(args.github_output, admitted, refusal)
        except (OSError, AdmissionError):
            print("CI output admission: step_output_unavailable")
            return 1
    print(json.dumps({"scope": args.mode, "capacity_admitted": admitted, "native_proof": False,
        "refusal_written": refusal, "code": code, **summary}, sort_keys=True))
    return 0 if admitted else 1


if __name__ == "__main__":
    raise SystemExit(main())
