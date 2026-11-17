#!/usr/bin/env python3
"""Run scientific fixture tests with pytest supplied from a separate support env.

Usage: scientific-python scripts/run_pinned_tests.py --pytest-support PATH [pytest args...]
No package is installed or modified by this runner.
"""

import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--pytest-support", type=Path, required=True)
    options, pytest_args = parser.parse_known_args()
    support = options.pytest_support.resolve()
    if not (support / "pytest").is_dir():
        parser.error("--pytest-support must contain the pytest package directory")
    # Keep scientific-environment distributions ahead of pytest-support
    # metadata; this path supplies pytest, not modelling dependencies.
    sys.path.append(str(support))
    os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    import pytest

    raise SystemExit(pytest.main(pytest_args))


if __name__ == "__main__":
    main()
