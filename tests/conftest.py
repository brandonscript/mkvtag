from pathlib import Path

import pytest


@pytest.fixture(scope="function", autouse=True)
def clean_test_files():
    import os

    test_dir = Path("./tests")
    for file in test_dir.glob("*.json"):
        os.remove(file)

    yield

    for file in test_dir.glob("*.json"):
        os.remove(file)
