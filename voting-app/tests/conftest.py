"""Pytest bootstrap for the FRCA Election App test suite.

app.py runs init_db()/migrate_db() at import time, against whatever DB_PATH
resolved to at module scope. Fixtures that reassign app_module.DB_PATH only
run after the import has already happened, so without this hook the very
first `import app` in a test session would create/migrate the REAL
data/frca_election.db.

Setting FRCA_DB_PATH here, at conftest module scope, fixes that: conftest is
imported before any test module, so app.py picks up the scratch path when it
is first imported. Per-test isolation is unchanged. Fixtures still
monkeypatch app_module.DB_PATH to their own temp file, and that assignment
still wins for everything the tests actually exercise.
"""

import os
import tempfile

os.environ["FRCA_DB_PATH"] = os.path.join(
    tempfile.gettempdir(), "frca_pytest_import.db")
