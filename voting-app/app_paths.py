"""Where the app keeps its data, and where its bundled read-only files live.

Running from source, both are the app folder, as before. Running as the
installed (PyInstaller-frozen) program, the install folder under Program
Files is read-only and replaced on every upgrade, so data lives under
%ProgramData% instead, and templates/static come from the bundle folder.
"""

import os

DATA_DIR_ENV = "FRCA_DATA_DIR"
PROGRAM_DATA_FALLBACK = r"C:\ProgramData"
PRODUCT_FOLDER = "FRCA Election"


def resolve_data_dir(environ, frozen, base_dir):
    """Return the data folder: FRCA_DATA_DIR, else ProgramData when frozen,
    else <base_dir>/data."""
    override = environ.get(DATA_DIR_ENV)
    if override:
        return override
    if frozen:
        program_data = environ.get("ProgramData") or PROGRAM_DATA_FALLBACK
        return os.path.join(program_data, PRODUCT_FOLDER, "data")
    return os.path.join(base_dir, "data")


def resolve_bundle_dir(frozen, meipass, module_dir):
    """Return the folder holding templates, static and docs."""
    if frozen and meipass:
        return meipass
    return module_dir
