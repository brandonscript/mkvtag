import argparse
import subprocess
import time
from pathlib import Path

from watchdog.observers import Observer

from mkvtag.args import Args
from mkvtag.tagger import MkvTagger


def main():
    # check to make sure mkvpropedit is installed
    try:
        subprocess.run(["which", "mkvpropedit"], check=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        raise RuntimeError("mkvpropedit is not installed. Please install it.")

    parser = argparse.ArgumentParser()
    Args.path(parser)
    Args.log(parser)
    Args.timer(parser)
    Args.loops(parser)
    Args.clean(parser)
    Args.exc(parser)

    args, _ = parser.parse_known_args()

    path = Path(args.path)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.is_dir():
        raise NotADirectoryError(f"'{path}' is not a directory or cannot be accessed.")

    print(f"mkvtag is watching directory: {path}")

    tagger = MkvTagger(
        watch_dir=path, log_file=args.log, rename_exp=args.clean, exc=args.exc
    )
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
        ...
    observer.stop()
    observer.join()
    print("mkvtag has stopped.")


if __name__ == "__main__":
    main()
