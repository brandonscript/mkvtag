import json
import sys
import threading
from pathlib import Path

import pytest

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


def run_main_threaded(stop_event: threading.Event):
    """Runs the main function in a thread and exits when stop_event is set."""

    from mkvtag.run import main

    sys.argv.extend(
        [
            "./tests/fixtures_generated",
            "-l=-1",
            "-w=2",
            "--log=./tests/fixtures_generated/mkvtag.json",
            r"-x [._-]*(remux|\bavc|vc-1|x264)",
            "-c",
            "-e",
        ]
    )

    print("Starting app in separate thread...")

    # Run the blocking function until stopped
    thread = threading.Thread(target=main, daemon=True)
    thread.start()

    while thread.is_alive():
        if stop_event.is_set():
            print("\nStopping app thread...")
            break
        thread.join(0.1)  # Avoid blocking forever

    print("App thread stopped")


@pytest.mark.asyncio
async def test_run_generated(simulate_file_writes, stop_event):

    import asyncio
    import concurrent.futures

    loop = asyncio.get_running_loop()

    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Start the app in a thread
            future_main = executor.submit(run_main_threaded, stop_event)

            # Run the simulate_file_writes function
            await loop.run_in_executor(executor, simulate_file_writes, 6, 2048)
            executor.shutdown(wait=False)

            # Trigger stop event to cancel everything
            stop_event.set()

            # Wait for threads to shut down
            future_main.result()

        print("Done running test, all threads should be closed.")

    except asyncio.CancelledError:
        print("Test was cancelled.")
    finally:
        stop_event.set()


def test_renaming(prep_renames):
    from mkvtag.run import main

    # sys.argv.append("./mkvtag")
    sys.argv.append("./tests/fixtures_rename")
    # sys.argv.append("/Volumes/media/Downloads/#converted")
    sys.argv.append("-l=5")
    sys.argv.append("--log=./tests/fixtures_rename/mkvtag.json")
    sys.argv.append(r"-x [._-]*(remux|\bavc|vc-1|x264)")
    sys.argv.append("-e")

    main()


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
