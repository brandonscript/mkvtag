import argparse
import asyncio
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import cast

from pid import PidFile, PidFileAlreadyRunningError, PidFileError
from watchdog.observers import Observer

from mkvtag.args import Args, MkvTagArgs
from mkvtag.tagger import MkvTagger

observer = None
counter = 0


def stop_observer():
    global observer
    if observer:
        observer.stop()
        observer.join()


def signal_handler(sig, frame):
    global observer, counter
    counter = 0
    stop_observer()
    sys.exit("Signal received: stopping mkvtag")


def main(stop_event: threading.Event | None = None):

    global observer, counter
    try:
        signal.signal(signal.SIGINT, signal_handler)
    except ValueError as e:
        if "signal only works in main thread" in str(e):
            print(
                "\n *** Warning: cannot set signal handler in a thread, you may end up with orphaned processes.\n"
            )
        else:
            raise e

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

    try:
        with PidFile(".mkvtag", piddir=path):

            # print(f"init - pid, thread_id: {os.getpid(), threading.get_ident()}")
            tagger = MkvTagger(watch_dir=path, args=args)
            observer = Observer()
            observer.schedule(tagger, path, recursive=False)
            observer.start()
            try:
                tagger.queue_files(observer)
                start_time = time.time()
                while args.loops < 0 or counter < args.loops:
                    if stop_event and stop_event.is_set():
                        raise asyncio.CancelledError
                    elapsed_time = time.time() - start_time
                    if elapsed_time >= args.timer:
                        # if "pytest" in sys.modules:
                        #     print(f"\nApp loop {counter + 1} of {args.loops}")
                        counter += 1
                        start_time = time.time()
                        tagger.queue_files(observer)
                    time.sleep(1)

            except KeyboardInterrupt:
                print("\nKeyboardInterrupt: mkvtag was cancelled")
            except asyncio.CancelledError:
                print("\nmkvtag was cancelled inside a thread or asyncio loop")
            finally:
                stop_observer()
            print("\nmkvtag has stopped")

    except PidFileError as e:

        # try to delete the pid file if it exists
        try:
            Path(path / ".mkvtag").unlink(missing_ok=True)
        except Exception:
            pass

        stop_observer()

        err = f"mkvtag is already running in '{path}'."
        if Path(path / ".mkvtag").exists():
            err += " If you are sure it is not, delete the '.mkvtag' file in that directory."

        raise PidFileAlreadyRunningError(err) from e


if __name__ == "__main__":
    main()
