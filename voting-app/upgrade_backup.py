"""Back up the database before a different app version migrates it.

The data folder holds last_version.txt, the version that last opened the
database. When the running version differs (or the file is missing, e.g.
data copied in from a source checkout), the database is copied to
data/backups/ first, so a schema migration can always be undone by hand.
"""

import os
import shutil

VERSION_FILE = "last_version.txt"
UNKNOWN_VERSION = "unknown"


def _read_last_version(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip() or UNKNOWN_VERSION
    except FileNotFoundError:
        return UNKNOWN_VERSION


def backup_before_upgrade(db_path, data_dir, current_version, now):
    """Copy db_path to <data_dir>/backups/ if the last version that opened it
    differs from current_version. Return the backup path, or None.

    Always records current_version as the last version afterwards.
    """
    version_path = os.path.join(data_dir, VERSION_FILE)
    last_version = _read_last_version(version_path)

    backup_path = None
    if os.path.exists(db_path) and last_version != current_version:
        backups_dir = os.path.join(data_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        backup_path = os.path.join(
            backups_dir,
            "%s.%s_%s" % (os.path.basename(db_path), last_version,
                          now.strftime("%Y-%m-%d_%H%M%S")))
        shutil.copy2(db_path, backup_path)
        # A WAL-mode database keeps recent writes in the -wal file; copy it
        # too so the backup is not missing them.
        if os.path.exists(db_path + "-wal"):
            shutil.copy2(db_path + "-wal", backup_path + "-wal")

    os.makedirs(data_dir, exist_ok=True)
    with open(version_path, "w", encoding="utf-8") as f:
        f.write(current_version)
    return backup_path
