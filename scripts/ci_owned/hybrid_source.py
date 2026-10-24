"""Test-owned binding for the standalone hybrid suite, not a controller.

source_suites.run_suites only executes direct __main__ files. This suite instead
requires two lazy byte loaders; its direct main deliberately refuses. Keep that
contract explicit without changing the historical 8+2+10/native qualifier.
The caller owns its unchanged audit fence, unittest runner and case reporter.
"""
from __future__ import annotations

import hashlib
import re
import types


def make_suite(test_loader, *, test_sha256, test_filename, source_loader,
               expected_sha256, filename, semantic_loader, semantic_sha256,
               semantic_filename):
    """Bind real reviewed test declarations; product reads stay in setUpClass."""
    if (not callable(test_loader) or type(test_sha256) is not str
            or re.fullmatch('[0-9a-f]{64}', test_sha256) is None
            or type(test_filename) is not str or not test_filename):
        raise ValueError('bound_test_source_required')
    raw = test_loader()
    if type(raw) is not bytes or len(raw) > 100_000:
        raise ValueError('test_source_bytes_or_size')
    if hashlib.sha256(raw).hexdigest() != test_sha256:
        raise ValueError('test_source_sha256_mismatch')
    module = types.ModuleType('explicit_hybrid_budget_source_tests')
    module.__file__ = test_filename
    exec(compile(raw, test_filename, 'exec', dont_inherit=True), module.__dict__)
    return module.source_suite(source_loader, expected_sha256=expected_sha256,
                               filename=filename, semantic_loader=semantic_loader,
                               semantic_sha256=semantic_sha256,
                               semantic_filename=semantic_filename)


if __name__ == '__main__':
    raise RuntimeError('explicit_loaders_and_existing_SOURCE_runner_required')
