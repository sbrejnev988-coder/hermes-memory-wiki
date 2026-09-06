"""Build hook that is inert when Hermes imports sibling plugin modules.

Hermes directory-provider discovery imports top-level *.py files.  Keep both
setuptools imports and setup() inside main(): importing this file must neither
parse Hermes' command-line arguments nor require packaging-only dependencies.
"""
from __future__ import annotations


def main() -> None:
    # Build-time dependencies must not be imported during provider discovery.
    import shutil
    from pathlib import Path

    from setuptools import setup
    from setuptools.command.build_py import build_py as _build_py

    class CleanBuildPy(_build_py):
        def run(self) -> None:
            build_lib = Path(self.build_lib)
            if build_lib.exists():
                shutil.rmtree(build_lib)
            super().run()

    setup(cmdclass={"build_py": CleanBuildPy})


if __name__ == "__main__":
    main()
