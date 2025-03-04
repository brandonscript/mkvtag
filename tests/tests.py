import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from conftest import make_test_file

sys.path.append(str(Path(__file__).parent.parent))


def test_run():
    from mkvtag.run import main

    # sys.argv.append("./mkvtag")
    sys.argv.append("./tests/fixtures")
    # sys.argv.append("/Volumes/media/Downloads/#converted")
    sys.argv.append("-l=5")
    sys.argv.append("--log=./tests/fixtures/mkvtag.json")
    sys.argv.append(r"-x [._-]*(remux|\bavc|vc-1|x264)")
    sys.argv.append("-e")

    main()


def run_main_threaded(
    stop_event: threading.Event,
    *,
    path: Path = Path("./tests/fixtures_generated"),
    loops: int = -1,
    wait_time: int = 2,
):
    """Runs the main function in a thread and exits when stop_event is set."""

    from mkvtag.run import main

    p = str(path)

    sys.argv.extend(
        [
            p,
            f"-l={loops}",
            f"-w={wait_time}",
            f"--log={path / "mkvtag.json"}",
            r"-x [._-]*(remux|\bavc|vc-1|x264)",
            "-c",
            "-e",
        ]
    )

    pid = threading.get_ident()
    print(f"Starting app in separate thread with pid: {pid}")
    main(stop_event)
    print(f"App thread (pid: {pid}) finished")


@pytest.mark.asyncio
async def test_run_generated(simulate_file_writes, stop_event):

    import asyncio
    import concurrent.futures

    generated_fixtures = Path("./tests/fixtures_generated")

    # Create one file to start with
    make_test_file(generated_fixtures, add_to_log=True)

    # wait 2s to ensure the file's age is > wait_time
    time.sleep(2)

    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Start the app in a thread
            future_main = executor.submit(run_main_threaded, stop_event)
            future_simulate = executor.submit(
                simulate_file_writes, files=6, chunk_size=4096
            )

            for future in concurrent.futures.as_completed(
                [future_main, future_simulate]
            ):
                assert future.result() is None
                if future == future_simulate:
                    print("Done generating files, waiting for main thread to finish...")
                    all_done = False
                    while all_done is False:
                        # read json file and check if there are any not done or failed files
                        log_json = json.loads(
                            (generated_fixtures / "mkvtag.json").read_text()
                        )
                        all_done = all(
                            file["status"] in ["done", "failed"]
                            for file in log_json.values()
                        )
                        time.sleep(1)
                    print("Cancelling main thread...")
                    stop_event.set()
                    future_main.result(timeout=5)
                    executor.shutdown(wait=False)
                    print("Main thread cancelled.")
                    break

        print("\nDone running test, all threads should be closed.")

        log_json = json.loads((generated_fixtures / "mkvtag.json").read_text())
        assert len(log_json) == 7

        # assert all files are "done"
        for file in log_json.values():
            assert (
                file["status"] == "done"
            ), f"{file['name']} is '{file['status']}', expected 'done'"

    except asyncio.CancelledError:
        print("Test was cancelled.")
    finally:
        stop_event.set()


@pytest.mark.asyncio
async def test_pid_lock(stop_event):

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Start two app threads
        future_main_1 = executor.submit(
            run_main_threaded, stop_event, loops=1, wait_time=1
        )
        time.sleep(0.5)
        future_main_2 = executor.submit(
            run_main_threaded, stop_event, loops=3, wait_time=1
        )

        for future in concurrent.futures.as_completed([future_main_1, future_main_2]):
            if future == future_main_2:
                with pytest.raises(Exception):
                    future.result()
            else:
                assert future.result() is None


def test_renaming(prep_renames):
    from mkvtag.run import main

    rename_fixtures = Path("./tests/fixtures_rename")
    # sys.argv.append("./mkvtag")
    sys.argv.append(str(rename_fixtures))
    # sys.argv.append("/Volumes/media/Downloads/#converted")
    sys.argv.append("-l=5")
    sys.argv.append("-w=1")
    sys.argv.append(f"--log={rename_fixtures}/mkvtag.json")
    sys.argv.append(r"-x [._-]*(remux|\bavc|vc-1|x264)")
    sys.argv.append("-e")

    main()

    # Check output dir for 4 tiles and make sure none contain "remux" (case insensitive)
    files = list(rename_fixtures.glob("*.mkv"))
    assert len(files) == 4
    for file in files:
        assert "remux" not in file.name.lower()

    # make sure the log file has 4 files with status "done" and none have "remux" in the key or name
    log_data = json.loads((rename_fixtures / "mkvtag.json").read_text())
    assert len(log_data) == 4
    for file in log_data.values():
        assert "remux" not in file["name"].lower()
        assert file["status"] == "done"

    assert all("remux" not in k.lower() for k in log_data.keys())


def test_existing_log_json(existing_log_json: tuple[dict[str, dict[str, Any]], Path]):
    from mkvtag.run import main

    [initial_log_json, log_file] = existing_log_json

    # sys.argv.append("./mkvtag")
    sys.argv.append("./tests/fixtures")
    # sys.argv.append("/Volumes/media/Downloads/#converted")
    sys.argv.append("-l=5")
    sys.argv.append("-w=2")
    sys.argv.append(f"--log={log_file}")
    sys.argv.append(r"-x [._-]*(remux|\bavc|vc-1|x264)")
    sys.argv.append("-e")

    done_files = {k: v for k, v in initial_log_json.items() if v["status"] == "done"}
    new_files = {k: v for k, v in initial_log_json.items() if v["status"] == "new"}
    failed_files = {k: v for k, v in initial_log_json.items() if "failed" in k}
    waiting_files = {
        k: v for k, v in initial_log_json.items() if v["status"] == "waiting"
    }

    total_expected_done = (
        len(done_files | new_files | waiting_files) - 1
    )  # -1 for an extra failed file

    main()

    after_log_data = json.loads(log_file.read_text())

    done_files_after = {
        k: v for k, v in after_log_data.items() if v["status"] == "done"
    }
    assert len(done_files_after) == total_expected_done
    new_files_after = {k: v for k, v in after_log_data.items() if v["status"] == "new"}
    assert len(new_files_after) == 0
    failed_files_after = {
        k: v for k, v in after_log_data.items() if v["status"] == "failed"
    }
    assert (
        len(failed_files_after) == len(failed_files) + 1
    )  # +1 for the extra failed file
    waiting_files_after = {
        k: v for k, v in after_log_data.items() if v["status"] == "waiting"
    }
    assert len(waiting_files_after) == 0


@pytest.mark.parametrize("exc", [True, False])
def test_bad_log_file(exc: bool):
    from mkvtag.run import main

    bad_log = Path("./tests/mkvtag-test-bad.json")
    bad_log.write_text('{}{"file": { "name": "test.mkv" } }')

    sys.argv.append("./tests/fixtures")
    sys.argv.append("")
    sys.argv.append("-l=2")
    sys.argv.append("-t=1")
    sys.argv.append(f"--log={bad_log}")
    sys.argv.append(f"-e={exc}")

    if exc:
        with pytest.raises(json.decoder.JSONDecodeError):
            main()
    else:
        main()
