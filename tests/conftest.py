import copy
from pathlib import Path

import pytest

from bafu_community_fixes.pipeline import import_database

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_bafu() -> Path:
    return FIXTURES / "raw_bafu.xml"


@pytest.fixture(scope="session")
def _imported():
    return import_database(FIXTURES / "raw_bafu.xml", strict=True)


@pytest.fixture
def db(_imported):
    """A fresh copy of the imported fixture database."""
    return copy.deepcopy(_imported)


@pytest.fixture
def dataset(db):
    return next(iter(db))
