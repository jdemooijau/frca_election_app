"""Tests for the database backup taken before a new version migrates it."""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade_backup import backup_before_upgrade

NOW = datetime(2026, 10, 18, 19, 30, 5)


def _db(tmp_path, content=b"sqlite bytes"):
    db = tmp_path / "frca_election.db"
    db.write_bytes(content)
    return db


def _version_file(tmp_path):
    return tmp_path / "last_version.txt"


def test_no_db_no_backup(tmp_path):
    result = backup_before_upgrade(str(tmp_path / "frca_election.db"), str(tmp_path), "1.4.0", NOW)
    assert result is None
    assert _version_file(tmp_path).read_text() == "1.4.0"


def test_same_version_no_backup(tmp_path):
    db = _db(tmp_path)
    _version_file(tmp_path).write_text("1.4.0")
    assert backup_before_upgrade(str(db), str(tmp_path), "1.4.0", NOW) is None
    assert not (tmp_path / "backups").exists()


def test_backup_on_version_change(tmp_path):
    db = _db(tmp_path)
    _version_file(tmp_path).write_text("1.3.1")
    result = backup_before_upgrade(str(db), str(tmp_path), "1.4.0", NOW)
    assert result.endswith(os.path.join("backups", "frca_election.db.1.3.1_2026-10-18_193005"))
    with open(result, "rb") as f:
        assert f.read() == b"sqlite bytes"
    assert _version_file(tmp_path).read_text() == "1.4.0"


def test_backup_when_no_version_file(tmp_path):
    db = _db(tmp_path)
    result = backup_before_upgrade(str(db), str(tmp_path), "1.4.0", NOW)
    assert ".unknown_" in os.path.basename(result)


def test_backup_copies_wal_file(tmp_path):
    db = _db(tmp_path)
    (tmp_path / "frca_election.db-wal").write_bytes(b"wal bytes")
    _version_file(tmp_path).write_text("1.3.1")
    result = backup_before_upgrade(str(db), str(tmp_path), "1.4.0", NOW)
    with open(result + "-wal", "rb") as f:
        assert f.read() == b"wal bytes"


def _import_app(env_overrides):
    import subprocess
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {k: v for k, v in os.environ.items() if k not in ("FRCA_DB_PATH", "FRCA_DATA_DIR")}
    env.update(env_overrides)
    return subprocess.run([sys.executable, "-c", "import app"], cwd=app_dir,
                          env=env, capture_output=True, text=True, timeout=60)


def test_app_startup_backs_up_copied_in_database(tmp_path):
    import sqlite3
    sqlite3.connect(str(tmp_path / "frca_election.db")).close()
    proc = _import_app({"FRCA_DATA_DIR": str(tmp_path)})
    assert proc.returncode == 0, proc.stderr
    from version import __version__
    assert (tmp_path / "last_version.txt").read_text() == __version__
    assert len(os.listdir(tmp_path / "backups")) == 1
    assert "Backup before upgrade: " in proc.stdout


def test_app_startup_skips_backup_with_db_override(tmp_path):
    proc = _import_app({"FRCA_DATA_DIR": str(tmp_path),
                        "FRCA_DB_PATH": str(tmp_path / "scratch.db")})
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "last_version.txt").exists()
