import pytest

from taskflows.db import create_missing_tables


@pytest.fixture
def tables():
    create_missing_tables()
