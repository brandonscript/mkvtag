import os
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path

import pytest

fixtures_dir = Path("./tests/fixtures")
fixtures_safe_dir = Path("./tests/fixtures_safe")
generated_dir = Path("./tests/fixtures_generated")


@pytest.fixture(scope="function", autouse=True)
def clean_test_files():
    import os

    test_dirs = [fixtures_dir, generated_dir]
    for file in [f for d in [d.glob("*.json") for d in test_dirs] for f in d]:
        os.remove(file)

    yield

    for file in [f for d in [d.glob("*.json") for d in test_dirs] for f in d]:
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


@pytest.fixture(scope="function", autouse=False)
def missing_log():
    log = Path("./tests/mkvtag-test-missing.json")
    log.unlink(missing_ok=True)

    yield log

    log.unlink(missing_ok=True)


thread_enabled_file = generated_dir / ".thread_enabled"


def kill_orphaned_test():
    pid = os.getpid()
    newest_timestamp = datetime.now()

    def _parse_timestamp(x):
        raw = x.split()[8]
        now = datetime.now()
        try:
            t = datetime.strptime(raw, "%H:%M%p")
            return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        except ValueError:
            try:
                d = datetime.strptime(raw, "%b%d%Y")
                return now.replace(
                    year=d.year, month=d.month, day=d.day, second=0, microsecond=0
                )
            except ValueError:
                raise ValueError(
                    f"Could not parse timestamp: {raw} (tried %H:%M%p and %b%d%Y)"
                )

    def _filter(x):
        if not x.strip() or "grep" in x:
            return False
        xpid = int(x.split()[1])
        if pid == xpid:
            return False  # exclude the current process

        if "debugpy" in x:
            timestamp = _parse_timestamp(x)
            nonlocal newest_timestamp
            # compare absolute time difference - if more than 2 minutes,
            # then the process is likely orphaned
            return (newest_timestamp - timestamp).total_seconds() > 120
        return True

    psaux = "ps aux -O lstart" if sys.platform == "darwin" else "ps aux --sort=-lstart"
    orphaned_tests = os.popen(f"{psaux} | grep -e 'mkvtag.*pytest'").read()
    lines = orphaned_tests.split("\n")
    newest_timestamp = _parse_timestamp(lines[0] if lines else "")
    lines = list(filter(_filter, lines))
    if lines:
        print("Found orphaned tests running, killing them...")
        for line in lines:
            pid = line.split()[1]
            os.system(f"kill -9 {pid}")


@pytest.fixture(scope="function", autouse=False)
def thread_controller():

    kill_orphaned_test()

    # create a file to indicate that the thread should be allowed to create files
    thread_enabled_file.parent.mkdir(parents=True, exist_ok=True)
    thread_enabled_file.touch(exist_ok=True)
    yield
    thread_enabled_file.unlink(missing_ok=True)

    kill_orphaned_test()


def signal_handler(sig, frame):
    """Handle test interruptions (e.g., Ctrl+C, VS Code stop)."""
    print(f"Received signal {sig}, stopping threads...")
    thread_enabled_file.unlink(missing_ok=True)


@pytest.fixture(scope="session", autouse=True)
def myfixture(request):
    def finalizer():
        thread_enabled_file.unlink(missing_ok=True)

    request.addfinalizer(finalizer)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGQUIT, signal_handler)
signal.signal(signal.SIGABRT, signal_handler)


@pytest.fixture
def stop_event(request):
    """Creates a stop event that gets triggered when the test exits."""
    event = threading.Event()

    def cleanup():
        print("Stopping simulate_file_writes due to test interruption.")
        event.set()

    request.addfinalizer(cleanup)
    return event


@pytest.fixture(scope="function", autouse=False)
def simulate_file_writes(
    thread_controller, stop_event
):  # Runs a generator that creates and writes to several files in the test directory over a period of time
    import random
    import string
    import time

    prefix = "gen_"
    for file in generated_dir.glob(f"{prefix}*"):
        file.unlink()

    generated_dir.mkdir(parents=True, exist_ok=True)

    bps_content = (fixtures_dir / "sample_960x540.mkv").read_bytes()
    no_bps_content = (fixtures_safe_dir / "sample_960x540_no_bps.mkv").read_bytes()

    # pid = os.getpid()

    def write_files(files: int = 10, chunk_size: int = 2048):
        for i in range(files):
            is_even = i % 2 == 0
            file_content = bps_content if is_even else no_bps_content
            midfix = "" if is_even else "_no_bps_"
            if not thread_enabled_file.exists():
                # print(f"gen/test ({pid}) thread is disabled")
                return
            time.sleep(1)
            file_name = "".join(random.choices(string.ascii_letters, k=10))
            file = (generated_dir / f"{prefix}{midfix}{file_name}").with_suffix(".mkv")
            # Write the file in increments to simulate a file being written to
            with file.open("wb") as f:
                for i in range(0, len(file_content), chunk_size):
                    if not thread_enabled_file.exists() or stop_event.is_set():
                        # print(f"gen/test ({pid}) thread is disabled")
                        return
                    f.write(file_content[i : i + chunk_size])
                    f.flush()
                    time.sleep(0.01)  # 10 ms
                # print(f"gen/test ({pid}) wrote file:", file)
        time.sleep(10)
        thread_enabled_file.unlink(missing_ok=True)

    def delete_files():
        for file in generated_dir.glob(f"{prefix}*"):
            file.unlink()

    def wrapper():
        return write_files

    yield wrapper()

    delete_files()
