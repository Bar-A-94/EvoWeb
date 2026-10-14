import pytest

from evoweb.paths import ensure_data


@pytest.fixture(scope="session", autouse=True)
def _data():
    """The benchmark and its translations, the latest from Hugging Face."""
    ensure_data()
