import argparse
import asyncio
import subprocess
import time
from pathlib import Path
from typing import cast

from watchdog.observers import Observer

from mkvtag.args import Args, MkvTagArgs
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
    Args.wait(parser)
    Args.loops(parser)
    Args.clean(parser)
    Args.precheck(parser)
    Args.exc(parser)

    _args, _ = parser.parse_known_args()
    args = cast(MkvTagArgs, _args)

    path = Path(args.path)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.is_dir():
        raise NotADirectoryError(f"'{path}' is not a directory or cannot be accessed.")

    print(f"mkvtag is watching directory: {path}")

    # print(f"init - pid, thread_id: {os.getpid(), threading.get_ident()}")
    tagger = MkvTagger(watch_dir=path, args=args)
    observer = Observer()
    observer.schedule(tagger, path, recursive=False)
    observer.start()

    counter = 0
    try:
        while args.loops < 0 or counter < args.loops:
            counter += 1
            tagger.refresh()
            tagger.process_dir()
            time.sleep(args.timer)

    except KeyboardInterrupt:
        ...
    except asyncio.CancelledError:
        print("\nmkvtag was cancelled inside an asyncio loop")
    finally:
        observer.stop()
        observer.join()
    print("\nmkvtag has stopped")


if __name__ == "__main__":
    main()
