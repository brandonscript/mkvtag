import argparse
import os
import subprocess
import time
from pathlib import Path

from watchdog.observers import Observer

from mkvtag.constants import SLEEP_TIME
from mkvtag.tagger import MkvTagger


def main():
    # check to make sure mkvpropedit is installed
    try:
        subprocess.run(["which", "mkvpropedit"], check=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        raise RuntimeError("mkvpropedit is not installed. Please install it.")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path", nargs="?", default=os.getcwd(), help="Directory to watch"
    )

    parser.add_argument(
        "--log",
        action="store",
        type=Path,
        default=os.getenv("MKVTAG_LOGFILE", None),
    )

    parser.add_argument(
        "-t",
        "--timer",
        type=int,
        default=os.getenv("MKVTAG_TIMER", SLEEP_TIME),
        help="Number of seconds to wait/loop",
    )

    parser.add_argument(
        "-l",
        "--loops",
        type=int,
        default=os.getenv("MKVTAG_LOOPS", -1),
        help="Number of loops to run before exiting (default: -1 to run indefinitely)",
    )

    parser.add_argument(
        "-x",
        "--clean",
        action="store",
        type=str,
        default=os.getenv("MKVTAG_CLEAN", None),
        help="A case-insensitive regular expression that all matching substrings will be stripped from the filename",
    )
    args, _ = parser.parse_known_args()

    path = Path(args.path)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.is_dir():
        raise NotADirectoryError(f"'{path}' is not a directory or cannot be accessed.")

    print(f"mkvtag is watching directory: {path}")

    tagger = MkvTagger(watch_dir=path, log_file=args.log, rename_exp=args.clean)
    observer = Observer()
    observer.schedule(tagger, path, recursive=False)
    observer.start()

    counter = 0
    try:
        while args.loops < 0 or counter < args.loops:
            counter += 1
            time.sleep(args.timer)
            tagger.process_dir()

    except KeyboardInterrupt:
        observer.stop()
        # remove the log file
        # if tagger.log_file.exists():
        #     tagger.log_file.unlink()
    observer.join()


if __name__ == "__main__":
    main()
