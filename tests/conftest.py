import json
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

fixtures_dir = Path("./tests/fixtures")
fixtures_safe_dir = Path("./tests/fixtures_safe")
generated_dir = Path("./tests/fixtures_generated")


@pytest.fixture(scope="function", autouse=True)
def rm_pytest_args():
    print("rm_pytest_args", sys.argv)
    if "--" in sys.argv or not any("pytest" in arg for arg in sys.argv):
        return

    pytest_arg_index = [i for i, arg in enumerate(sys.argv) if "pytest" in arg][0]
    sys.argv = sys.argv[: pytest_arg_index + 1]

    yield


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


@pytest.fixture(scope="function", autouse=True)
def kill_orphaned_tests():
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

    # create a file to indicate that the thread should be allowed to create files
    thread_enabled_file.parent.mkdir(parents=True, exist_ok=True)
    thread_enabled_file.touch(exist_ok=True)
    yield
    thread_enabled_file.unlink(missing_ok=True)


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


def make_test_file(
    dest_dir: Path,
    *,
    with_bps: bool = False,
    chunk_size: int = 2048,
    stop_event: threading.Event | None = None,
    add_to_log: bool = False,
):
    """Create a test file in the destination directory."""
    import random
    import string

    prefix = "gen_"
    bps_content = (fixtures_dir / "sample_960x540.mkv").read_bytes()
    no_bps_content = (fixtures_safe_dir / "sample_960x540_no_bps.mkv").read_bytes()

    midfix = "" if with_bps else "_no_bps_"
    file_content = bps_content if with_bps else no_bps_content
    file_name = "".join(random.choices(string.ascii_letters, k=10))
    file = (dest_dir / f"{prefix}{midfix}{file_name}").with_suffix(".mkv")
    # Write the file in increments to simulate a file being written to
    with file.open("wb") as f:
        for i in range(0, len(file_content), chunk_size):
            if not thread_enabled_file.exists() or (s := stop_event) and s.is_set():
                # print(f"gen/test ({pid}) thread is disabled")
                return
            f.write(file_content[i : i + chunk_size])
            f.flush()
            time.sleep(0.002)  # 2 ms

    if add_to_log:
        log = dest_dir / "mkvtag.json"
        if log.exists():
            with log.open("r") as f:
                data = json.load(f)
        else:
            data = {}
        data[file.name] = {
            "name": file.name,
            "mtime": datetime.fromtimestamp(file.stat().st_mtime).isoformat(),
            "size": file.stat().st_size,
            "failed_count": 0,
            "status": "new",
        }
        with log.open("w") as f:
            json.dump(data, f, indent=2)


@pytest.fixture(scope="function", autouse=False)
def simulate_file_writes(
    thread_controller,
    stop_event,
):  # Runs a generator that creates and writes to several files in the test directory over a period of time
    import time

    prefix = "gen_"
    for file in generated_dir.glob(f"{prefix}*"):
        file.unlink()

    generated_dir.mkdir(parents=True, exist_ok=True)

    # pid = os.getpid()

    def write_files(*, files: int = 10, chunk_size: int = 4096):
        for i in range(files):
            if not thread_enabled_file.exists():
                # print(f"gen/test ({pid}) thread is disabled")
                return
            time.sleep(0.5)
            make_test_file(
                generated_dir,
                with_bps=i == 2,
                chunk_size=chunk_size,
                stop_event=stop_event,
            )
        thread_enabled_file.unlink(missing_ok=True)
        print(f"\nSimulated file writes complete, created {files} files.")

    def delete_files():
        for file in generated_dir.glob(f"{prefix}*"):
            file.unlink()

    def wrapper():
        return write_files

    yield wrapper()

    delete_files()


@pytest.fixture(scope="function", autouse=True)
def prep_renames():
    # delete all files in the fixtures_rename directory
    rename_dir = Path("./tests/fixtures_rename")
    for file in rename_dir.glob("*"):
        file.unlink()
    rename_dir.mkdir(parents=True, exist_ok=True)
    # copy '(fixtures_dir / "sample_960x540.mkv")' to the rename directory several times with new names

    m = [
        "Gangs.of.New.York.2002.BluRay.1080p.x265.10-bit.DTS-HD.MA.5.1.FraMeSToR.mkv",
        "Dredd.2012.1080p.BluRay.AVC.REMUX.DTS-HD.MA.7.1.x264-AllYgaTrZ.mkv",
        "The.Matrix.1999.1080p.BluRay.REMUX.DTS-HD.MA.7.1.x264-TayTO.mkv",
        "John.Wick.2014.1080p.BluRay.REMUX.DTS-HD.MA.7.1.x264-PHD.mkv",
    ]

    for name in m:
        (rename_dir / name).write_bytes(
            (fixtures_dir / "sample_960x540.mkv").read_bytes()
        )

    yield

    # delete all files in the fixtures_rename directory
    for file in rename_dir.glob("*"):
        file.unlink()


@pytest.fixture(scope="function", autouse=False)
def existing_log_json():
    log = fixtures_dir / "mkvtag.json"
    if log.exists():
        log.unlink()

    # Create a new log for each file in the fixtures directory
    # - if file contains "failed", make sure it has a failed_count > 0
    # - set status of the rest into 3 categories: "done", "waiting", "new" (in order, with 1/3 of the files in each category)

    files = list(fixtures_dir.glob("*.mkv"))
    log_data = {}
    files.sort(key=lambda x: x.name)
    third = len(files) // 3
    status = "new"
    for i, file in enumerate(files):
        if i < third:
            status = "done"
        elif i < 2 * third:
            status = "waiting"
        else:
            status = "new"
        failed_count = 1 if "failed" in file.name else 0
        status = "failed" if failed_count > 0 else status
        log_data[file.name] = {
            "name": file.name,
            "mtime": datetime.fromtimestamp(file.stat().st_mtime).isoformat(),
            "size": file.stat().st_size,
            "failed_count": failed_count,
            "status": status,
        }

    log.write_text(json.dumps(log_data, indent=2))

    yield [log_data, log]

    log.unlink()
