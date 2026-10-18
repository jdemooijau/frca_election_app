"""Tests for the database backup taken before a new version migrates it.

The version that last opened a database is stored inside it (settings key
app_version), so a database copied in from elsewhere carries its own
version, or none.
"""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from upgrade_backup import backup_before_upgrade, read_db_version

NOW = datetime(2026, 10, 18, 19, 30, 5)


def _db(tmp_path, version=None, name="frca_election.db"):
    path = tmp_path / name
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if version is not None:
        conn.execute("INSERT INTO settings VALUES ('app_version', ?)", (version,))
    conn.commit()
    conn.close()
    return path


def test_read_db_version_values(tmp_path):
    assert read_db_version(str(_db(tmp_path, "1.3.1"))) == "1.3.1"
    assert read_db_version(str(_db(tmp_path, None, "noversion.db"))) == "unknown"
    bare = tmp_path / "bare.db"
    sqlite3.connect(str(bare)).close()
    assert read_db_version(str(bare)) == "unknown"


def test_no_db_no_backup(tmp_path):
    assert backup_before_upgrade(str(tmp_path / "frca_election.db"), str(tmp_path), "1.4.0", NOW) is None
    assert not (tmp_path / "backups").exists()


def test_same_version_no_backup(tmp_path):
    db = _db(tmp_path, "1.4.0")
    assert backup_before_upgrade(str(db), str(tmp_path), "1.4.0", NOW) is None
    assert not (tmp_path / "backups").exists()


def test_backup_on_version_change(tmp_path):
    db = _db(tmp_path, "1.3.1")
    result = backup_before_upgrade(str(db), str(tmp_path), "1.4.0", NOW)
    assert result.endswith(os.path.join("backups", "frca_election.db.1.3.1_2026-10-18_193005"))
    assert read_db_version(result) == "1.3.1"


def test_backup_when_db_has_no_version(tmp_path):
    db = _db(tmp_path, None)
    result = backup_before_upgrade(str(db), str(tmp_path), "1.4.0", NOW)
    assert ".unknown_" in os.path.basename(result)


def test_copied_in_db_backed_up_even_after_fresh_install_ran(tmp_path):
    # Fresh install ran once (its db said 1.4.0), then an old source db
    # without a version was copied over it. The copied db must be backed up.
    _db(tmp_path, "1.4.0")
    os.remove(tmp_path / "frca_election.db")
    db = _db(tmp_path, None)
    assert backup_before_upgrade(str(db), str(tmp_path), "1.4.0", NOW) is not None


def test_backup_copies_wal_file(tmp_path):
    db = _db(tmp_path, "1.3.1")
    (tmp_path / "frca_election.db-wal").write_bytes(b"wal bytes")
    result = backup_before_upgrade(str(db), str(tmp_path), "1.4.0", NOW)
    with open(result + "-wal", "rb") as f:
        assert f.read() == b"wal bytes"


def _import_app(env_overrides):
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {k: v for k, v in os.environ.items() if k not in ("FRCA_DB_PATH", "FRCA_DATA_DIR")}
    env.update(env_overrides)
    return subprocess.run([sys.executable, "-c", "import app"], cwd=app_dir,
                          env=env, capture_output=True, text=True, timeout=60)


def test_app_startup_backs_up_copied_in_database_and_records_version(tmp_path):
    _db(tmp_path, None)
    proc = _import_app({"FRCA_DATA_DIR": str(tmp_path)})
    assert proc.returncode == 0, proc.stderr
    from version import __version__
    assert read_db_version(str(tmp_path / "frca_election.db")) == __version__
    assert len(os.listdir(tmp_path / "backups")) == 1
    assert "Backup before upgrade: " in proc.stdout


def test_app_startup_second_run_makes_no_new_backup(tmp_path):
    _db(tmp_path, None)
    _import_app({"FRCA_DATA_DIR": str(tmp_path)})
    _import_app({"FRCA_DATA_DIR": str(tmp_path)})
    assert len(os.listdir(tmp_path / "backups")) == 1


def test_app_startup_skips_backup_with_db_override(tmp_path):
    proc = _import_app({"FRCA_DATA_DIR": str(tmp_path),
                        "FRCA_DB_PATH": str(tmp_path / "scratch.db")})
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "backups").exists()
