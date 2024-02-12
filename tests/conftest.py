import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--pg-url",
        action="store",
        help="URL to a PostgreSQL database that should be used for testing. A temporary schema will be created in this database.",
    )
