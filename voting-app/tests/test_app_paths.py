"""Tests for data-folder and bundle-folder resolution (app_paths.py)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_paths import resolve_data_dir, resolve_bundle_dir


def test_env_override_wins():
    assert resolve_data_dir({"FRCA_DATA_DIR": r"D:\x"}, True, r"C:\app") == r"D:\x"


def test_env_override_wins_from_source():
    assert resolve_data_dir({"FRCA_DATA_DIR": r"D:\x"}, False, r"C:\app") == r"D:\x"


def test_frozen_uses_programdata():
    env = {"ProgramData": r"C:\ProgramData"}
    assert resolve_data_dir(env, True, r"C:\app") == r"C:\ProgramData\FRCA Election\data"


def test_frozen_without_programdata_falls_back():
    assert resolve_data_dir({}, True, r"C:\app") == r"C:\ProgramData\FRCA Election\data"


def test_frozen_path_with_spaces():
    env = {"ProgramData": r"C:\Program Data Odd"}
    assert resolve_data_dir(env, True, r"C:\app").endswith(r"Odd\FRCA Election\data")


def test_source_uses_app_folder():
    assert resolve_data_dir({}, False, r"C:\app") == r"C:\app\data"


def test_bundle_dir_frozen_and_source():
    assert resolve_bundle_dir(True, r"C:\b\_internal", r"C:\x") == r"C:\b\_internal"
    assert resolve_bundle_dir(False, None, r"C:\x") == r"C:\x"
