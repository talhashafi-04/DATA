"""Ensure sibling modules (e.g. test_solution.py) resolve against this directory."""

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_TESTS_DIR_STR = str(_TESTS_DIR)
if _TESTS_DIR_STR not in sys.path:
    sys.path.insert(0, _TESTS_DIR_STR)
