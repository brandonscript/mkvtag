import json
import sys
from pathlib import Path

import pytest


def test_run():
    from mkvtag.run import main

    # sys.argv.append("./mkvtag")
    sys.argv.append("./tests/fixtures")
    # sys.argv.append("/Volumes/media/Downloads/#converted")
    sys.argv.append("-l=5")
    sys.argv.append("--log=./mkvtag/mkvtag.json")
    sys.argv.append(r"-x [._-]*(remux|\bavc|vc-1|x264)")
    sys.argv.append("-e")

    main()


def test_missing_log_file():
    from mkvtag.run import main

    missing_log = Path("./tests/mkvtag-test-missing.json")

    sys.argv.append("./tests/fixtures")
    sys.argv.append("-l=2")
    sys.argv.append("-t=1")
    sys.argv.append(f"--log={missing_log}")
    sys.argv.append("-e")

    main()

    # Check that the log file was created
    assert missing_log.exists()


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
