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


@pytest.fixture(scope="function", autouse=True)
def prep_test_files():

    if (
        file := Path(
            "./tests/fixtures/Gangs.of.New.York.2002.BluRay.1080p.DTS-HD.MA.5.1.FraMeSToR.mkv"
        )
    ).exists():
        file.rename(
            file.with_name(
                "Gangs.of.New.York.2002.BluRay.1080p.REMUX.AVC.DTS-HD.MA.5.1.FraMeSToR.mkv"
            )
        )

    yield
