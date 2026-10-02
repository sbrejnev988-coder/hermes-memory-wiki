#!/usr/bin/env python3
"""Regression: release wheel contains source/package data, never local bytecode caches."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wheel_contains_runtime_provider_and_excludes_local_build_caches() -> None:
    with tempfile.TemporaryDirectory(prefix="mw-wheel-content-") as tmp:
        result = subprocess.run(
            ["uv", "build", "--out-dir", tmp], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        assert result.returncode == 0, result.stdout.decode("utf-8", "replace")[-4000:]
        wheel = next(Path(tmp).glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            installed = Path(tmp) / 'installed'
            archive.extractall(installed)
        # Import the built artifact in a fresh interpreter. Source-code strings
        # cannot prove that the packaged runtime accepts owner settings or that
        # the session/background entrypoints forward the owning snapshot.
        env = dict(os.environ)
        home = Path(tmp) / 'home'
        env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home),
                   PYTHON_DOTENV_DISABLED='1', MEMORY_WIKI_SEMANTIC='0',
                   MEMORY_WIKI_BACKGROUND_JOBS_ENABLED='0', MEMORY_WIKI_EVENT_LEDGER_ENABLED='1',
                   MW_EXTRACTION_ENABLED='0')
        for key in list(env):
            if any(word in key.upper() for word in ('API_KEY', 'TOKEN', 'PASSWORD', 'SECRET')):
                env.pop(key)
        script = r'''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import memory_wiki as plugin
from memory_wiki import extractor
assert Path(plugin.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
home = Path(sys.argv[2])
home.mkdir()
seen = []
def capture(*args, **kwargs):
    seen.append(kwargs['extraction_settings'])
    return {'extracted': 0, 'persisted': 0, 'entries': [], 'error': ''}
plugin.extract_session_claims = capture
for provider, model in [('openai-codex', 'gpt-6-luna'), ('openrouter', 'xiaomi/mimo-v2.6-flash')]:
    (home / 'config.yaml').write_text(
        'plugins:\n  entries:\n    memory-wiki:\n      settings:\n        extraction:\n'
        '          enabled: true\n          provider: ' + provider + '\n          model: ' + model + '\n',
        encoding='utf-8')
    owner = plugin.MemoryWikiProvider()
    owner.initialize('synthetic-wheel-' + provider, hermes_home=str(home), bot_id='synthetic-wheel-owner')
    owner.project_scope = ''
    try:
        owner._extract_session_claims([{'role': 'user', 'content': 'Project Aster uses a violet release channel.'}])
        event_id = plugin._memory_events.capture_event(
            owner, plugin, 'Project Aster uses a violet release channel.', event_type='dialogue_turn',
            role='user', session_id=owner.session_id)
        assert event_id and plugin._background_jobs.enqueue_event(owner, 'extract_session_events', event_id)
        plugin._background_jobs.run_once(owner, plugin)
        assert len(seen) >= 2
        for snapshot in seen[-2:]:
            assert snapshot.home == home.resolve() and snapshot.provider == provider and snapshot.model == model
            assert snapshot.enabled and not snapshot.api_key
    finally:
        owner.shutdown()
print('BUILT_WHEEL_OWNER_PATHS_OK')
'''
        imported = subprocess.run([sys.executable, '-c', script, str(installed), str(home)],
                                  env=env, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=60)
        assert imported.returncode == 0, imported.stdout.decode('utf-8', 'replace')[-4000:]
        assert b'BUILT_WHEEL_OWNER_PATHS_OK' in imported.stdout
        required = {
            "memory_wiki/__init__.py",
            "memory_wiki/extractor.py",
            "memory_wiki/migrations.py",
            "memory_wiki/plugin.yaml",
            "memory_wiki/mcp-wrapper/server.py",
            "memory_wiki/context-coordination/manifest_protocol.py",
        }
        assert required.issubset(names), sorted(required.difference(names))
        assert not any("/__pycache__/" in name or name.endswith(".pyc") for name in names)


if __name__ == "__main__":
    test_wheel_contains_runtime_provider_and_excludes_local_build_caches()
    print("PASS test_wheel_contains_runtime_provider_and_excludes_local_build_caches")
