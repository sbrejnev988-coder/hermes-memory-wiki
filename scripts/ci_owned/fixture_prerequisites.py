"""Поставляемые portable prerequisites; без импорта provider, SDK или профиля."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile

# Эти два файла требуют ОТСУТСТВИЯ SDK и собственных process-global audit hooks.
# Это отдельный исполняемый roster, не optional tests и не blanket deselection.
SOURCE_SUITES = {
    'tests/test_p2_g4_identity_errors.py': ('G4Tests', 8),
    'tests/test_p2_g4_repair01.py': ('RepairTests', 2),
    'tests/test_foundation_ci_prerequisites.py': ('PrerequisiteControls', 10),
}
OFFLINE_SETTINGS = {
    'PYTHONDONTWRITEBYTECODE': '1',
    'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
    'PYTHON_DOTENV_DISABLED': '1',
    'HERMES_SECURITY_STRICT': '0',  # Только synthetic tests; strict gate отдельно.
    'MEMORY_WIKI_SEMANTIC': '0',
    'MEMORY_WIKI_DOCUMENT_AUTO_SCAN_CACHE': '0',
    'MEMORY_WIKI_BACKGROUND_JOBS_ENABLED': '0',
    'MEMORY_WIKI_GRAPH_EXTRACT_ENABLED': '0',
    'MEMORY_WIKI_GRAPH_AUTO_EXTRACT': '0',
    'MEMORY_WIKI_EVENT_LEDGER_ENABLED': '1',
    'MEMORY_WIKI_OBSERVATIONS_ENABLED': '1',
}
SYSTEM_KEYS = ('SystemRoot', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT')


def no_links(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
            raise ValueError('fixture_link_or_reparse_refused')
    return path


def clean_environment(root, ambient):
    """Никаких inherited auth/env/path/PYTHONPATH; все writable paths принадлежат root."""
    root = no_links(root)
    env = {name: ambient[name] for name in SYSTEM_KEYS if name in ambient}
    paths = {'HOME': root / 'user', 'USERPROFILE': root / 'user',
             'HERMES_HOME': root / 'app', 'APPDATA': root / 'user/roaming',
             'LOCALAPPDATA': root / 'user/local', 'TMPDIR': root / 'tmp',
             'TMP': root / 'tmp', 'TEMP': root / 'tmp'}
    for path in set(paths.values()):
        no_links(path).mkdir(parents=True, exist_ok=True)
    env.update({name: str(path) for name, path in paths.items()})
    env.update(OFFLINE_SETTINGS)
    return env


def source_fixture(key):
    """Standalone G4 entry owns its home even without historical ENV carriers.

    An explicit historical fixture remains supported, with its original home
    assertions. Otherwise allocate a new empty root under the caller's temp.
    This function must run before arming the suite's original audit hook.
    """
    explicit = os.environ.get(key)
    if explicit:
        return no_links(explicit)
    root = no_links(tempfile.mkdtemp(prefix='memory-wiki-source-'))
    env = clean_environment(root, os.environ)
    os.environ.clear()
    os.environ.update(env)
    os.environ[key] = str(root)
    return root


def suite_case_ids(source, relative):
    """Ровно shipped TestCase methods, без импорта тестов или SDK."""
    import ast
    owner, count = SOURCE_SUITES[relative]
    tree = ast.parse((Path(source) / relative).read_bytes())
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner]
    if len(classes) != 1:
        raise RuntimeError('source_suite_class_identity')
    names = sorted(node.name for node in classes[0].body
                   if isinstance(node, ast.FunctionDef) and node.name.startswith('test'))
    if len(names) != count or len(set(names)) != count:
        raise RuntimeError('source_suite_case_roster')
    return ['__main__.' + owner + '.' + name for name in names]


def native_pytest_args(source, source_result):
    """Exact split only after ALL SOURCE assertions ran successfully on these bytes."""
    import hashlib
    source = Path(source).resolve()
    if set(source_result) != set(SOURCE_SUITES):
        raise RuntimeError('source_suite_roster_incomplete')
    for relative, (_, count) in SOURCE_SUITES.items():
        row = source_result[relative]
        digest = hashlib.sha256((source / relative).read_bytes()).hexdigest()
        if (any(type(row.get(key)) is not int for key in ('exit_code', 'total', 'passed', 'failed', 'errors', 'skipped'))
                or row.get('case_ids') != suite_case_ids(source, relative)
                or row.get('exit_code') != 0 or row.get('total') != count
                or row.get('passed') != count or row.get('failed') != 0
                or row.get('errors') != 0 or row.get('skipped') != 0
                or row.get('sha256') != digest):
            raise RuntimeError('source_suite_not_qualified:' + relative)
    return ['--ignore=' + str(source / relative) for relative in SOURCE_SUITES]
