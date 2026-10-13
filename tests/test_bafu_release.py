"""Full-release test. Set BAFU_ECOSPOLD_DIR to the unzipped release to run it."""

import os
from pathlib import Path

import pytest

from bafu_community_fixes.pipeline import import_database

BAFU_DIR = os.environ.get("BAFU_ECOSPOLD_DIR")


@pytest.mark.skipif(not BAFU_DIR, reason="BAFU_ECOSPOLD_DIR not set")
def test_release_is_compliant_after_import():
    db = import_database(Path(BAFU_DIR), strict=True)
    assert len(db) > 0
