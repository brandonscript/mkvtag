import argparse
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from humanize import naturaltime
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

SLEEP_TIME = 5 if "pytest" in sys.modules else 30


class File:
    def __init__(self, file_path: Path):
        self.path = file_path
        self.mtime = self.get_mtime()
        self.size = self.get_size()
        self._processed = False

    def __repr__(self):
        return f"File({self.name}, {self.friendly_mtime}, {self.friendly_size}, done={self.processed})"

    @property
    def name(self):
        return self.path.name

    @property
    def friendly_mtime(self):
        """Use humanized time format from 'humanize' package"""

        return naturaltime(datetime.now() - datetime.fromtimestamp(self.mtime))

    def get_mtime(self):
        try:
            return Path(self.path).stat().st_mtime
        except FileNotFoundError:
            return 0.0

    @property
    def friendly_size(self):
        """Use humanized size format from 'humanize' package"""
        from humanize import naturalsize

        return naturalsize(self.size or 0)

    def get_size(self):
        try:
            return Path(self.path).stat().st_size
        except FileNotFoundError:
            return 0

    @property
    def processed(self):
        if self._processed:
            return True
        self._processed = is_processed(self, self.path.parent)
        return self._processed

    @classmethod
    def from_csv(cls, line: str, watch_dir: Path):
        name, mtime, size = line.strip().split(",")
        new = cls(watch_dir / name)
        new.mtime = float(mtime)
        new.size = int(size)
        return new

    def __eq__(self, other):
        return self.name == other.name


class MkvTagger(FileSystemEventHandler):
    current_files: dict[str, File]
    processed_files: dict[str, File]
    _active = False

    def __init__(self, watch_dir: Path = Path.cwd()):
        self.watch_dir = watch_dir
        self.log_file = self.watch_dir / "processed_files.txt"

        if self.log_file.exists():
            self.log_file.unlink()
            self.log_file.touch()

        print("Watching for new files...\n")

        self.scan()
        # print(self.current_files, self.processed_files)

        self.process_dir()

    def scan(self):
        self.current_files = scan_watch_dir(self.watch_dir)
        self.processed_files = load_processed_files(self.watch_dir)

    def process_dir(self):
        for file in self.current_files.values():
            if not self.is_file_done(file) and self.is_file_ready(file):
                self.process_file(file)

    def on_modified(self, event):
        if event.src_path.endswith(".mkv"):
            # print(f"File '{event.src_path}' has been modified.")
            # print(self.current_files, self.processed_files)
            # self.scan()
            file = File(Path(event.src_path))
            if not self.is_file_done(file) and self.is_file_ready(file):
                self.process_file(file)

    def is_file_done(self, file: File):
        current_size = file.get_size()
        if (
            (mkv := self.processed_files.get(file.name, None))
            and mkv.processed
            and mkv.size == current_size
        ):
            return True

        return False

    def is_file_ready(self, file: File):

        # if file is recently modified, skip
        if file.get_mtime() > time.time() - SLEEP_TIME:
            return False

        current_size = file.get_size()
        if (
            mkv := self.current_files.get(file.name, None)
        ) and mkv.size == current_size:
            return True

        # print(f"File '{file.name}' is not ready yet.")

        return False

    def process_file(self, file: File):

        if file.processed or self._active:
            return

        print(f"Processing file: {file.name}")
        self._active = True

        try:
            cmd: Sequence[str | Path] = [
                "mkvpropedit",
                "--add-track-statistics-tags",
                file.path,
            ]
            if sys.stdout.isatty():
                with subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ) as p:
                    with os.fdopen(sys.stdout.fileno(), "wb", closefd=False) as stdout:
                        for line in p.stdout or []:
                            stdout.write(line)
                            stdout.flush()
            else:
                res = subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
                if res.returncode != 0:
                    raise subprocess.CalledProcessError(res.returncode, res.args)
                print(f"Done\n")

            updated = self.current_files[file.name]
            updated.mtime = file.get_mtime()
            updated.size = file.get_size()
            updated._processed = True
            self.save_processed_files()
        except subprocess.CalledProcessError as e:
            proc_error = e.stderr.decode("utf-8")
            print(f"Error processing file {file.name}:\n{proc_error}")

        self._active = False

    def save_processed_files(self):
        new_processed_files = {
            mkv.name: mkv
            for mkv in self.current_files.values()
            if mkv.processed and not mkv.name in self.processed_files.keys()
        }
        with open(self.log_file, "a") as f:
            for mkv in new_processed_files.values():
                # skip if file is already in the log file
                if mkv.name in load_processed_files(self.watch_dir).keys():
                    continue
                f.write(f"{mkv.name},{mkv.mtime},{mkv.size}\n")

        self.processed_files = new_processed_files


def scan_watch_dir(watch_dir: Path):
    return {f.name: File(f) for f in Path(watch_dir).glob("*.mkv")}


def load_processed_files(watch_dir: Path):
    log_file = watch_dir / "processed_files.txt"
    processed_files = {}
    Path(log_file).touch(exist_ok=True)
    with open(log_file, "r") as f:
        processed_files = {
            mkv.name: mkv
            for mkv in [(File.from_csv(line, watch_dir)) for line in f]
            if mkv.name in scan_watch_dir(watch_dir).keys()
        }

        # mark all processed files as done
        for mkv in processed_files.values():
            mkv._processed = True

        return processed_files


def is_processed(file: File, watch_dir: Path):
    processed_files = load_processed_files(watch_dir)
    return bool(processed_files.get(file.name, None))


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
        "-t",
        "--timer",
        type=int,
        default=SLEEP_TIME,
        help="Number of seconds to wait/loop",
    )
    parser.add_argument(
        "-l",
        "--loops",
        type=int,
        default=-1,
        help="Number of loops to run before exiting (default: -1 to run indefinitely)",
    )
    args, _ = parser.parse_known_args()

    path = Path(args.path)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.is_dir():
        # try to create it
        try:
            path.mkdir(parents=True)
        except FileExistsError:
            pass
        except Exception as e:
            raise e
        raise NotADirectoryError(f"'{path}' is not a directory.")

    print(f"mkvtag is watching directory: {path}")

    tagger = MkvTagger(watch_dir=path)
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
        if tagger.log_file.exists():
            tagger.log_file.unlink()
    observer.join()


if __name__ == "__main__":
    main()
