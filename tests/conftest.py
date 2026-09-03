"""Repository-wide pytest isolation from the local MootOS database."""

import os
import tempfile
from pathlib import Path


_TEST_DATABASE_DIRECTORY = tempfile.TemporaryDirectory(
    prefix="mootos-pytest-"
)
_TEST_DATABASE_PATH = (
    Path(_TEST_DATABASE_DIRECTORY.name) / "mootos.db"
)

# Database paths are resolved by backend modules at import time. Set the
# repository's established override before pytest imports any test module so
# clean-db fixtures can never unlink the local development database.
os.environ["MOOTOS_DATABASE_PATH"] = str(_TEST_DATABASE_PATH)
