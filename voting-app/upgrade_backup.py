"""Back up the database before a different app version migrates it.

The version that last opened a database is stored inside it (settings key
app_version, written by app.py after migration). When the running version
differs, or the database has no version (e.g. copied in from a source
checkout), the database is copied to data/backups/ first, so a schema
migration can always be undone by hand.
"""

import os
import shutil
import sqlite3

VERSION_KEY = "app_version"
UNKNOWN_VERSION = "unknown"


def read_db_version(db_path):
    """The app version recorded in the database, or 'unknown'."""
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = ?",
                               (VERSION_KEY,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return UNKNOWN_VERSION
    return row[0] if row and row[0] else UNKNOWN_VERSION


def backup_before_upgrade(db_path, data_dir, current_version, now):
    """Copy db_path to <data_dir>/backups/ if the version recorded in it
    differs from current_version. Return the backup path, or None."""
    if not os.path.exists(db_path):
        return None
    db_version = read_db_version(db_path)
    if db_version == current_version:
        return None

    backups_dir = os.path.join(data_dir, "backups")
    os.makedirs(backups_dir, exist_ok=True)
    backup_path = os.path.join(
        backups_dir,
        "%s.%s_%s" % (os.path.basename(db_path), db_version,
                      now.strftime("%Y-%m-%d_%H%M%S")))
    shutil.copy2(db_path, backup_path)
    # A WAL-mode database keeps recent writes in the -wal file; copy it too
    # so the backup is not missing them.
    if os.path.exists(db_path + "-wal"):
        shutil.copy2(db_path + "-wal", backup_path + "-wal")
    return backup_path
