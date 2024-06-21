import argparse
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from humanize import naturaltime
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class File:
    def __init__(self, file_path: Path):
        self.path = file_path
        self.mtime = self.get_mtime()
        self.size = self.get_size()
        self.processed = False

    def __repr__(self):
        return f"File({self.name}, {self.friendly_mtime}, {self.friendly_size})"

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

    @classmethod
    def from_csv(cls, line: str, watch_dir: Path):
        name, mtime, size = line.strip().split(",")
        new = cls(watch_dir / name)
        new.mtime = float(mtime)
        new.size = int(size)
        return new

    def __eq__(self, other):
        return self.name == other.name


class ConvertedVideoHandler(FileSystemEventHandler):
    current_files: dict[str, File]
    processed_files: dict[str, File]

    def __init__(self, watch_dir: Path = Path.cwd()):
        self.watch_dir = watch_dir
        self.log_file = self.watch_dir / "processed_files.txt"
        print("Watching for new files...\n")

        self.scan()
        # print(self.current_files, self.processed_files)

        for file in self.current_files.values():
            if not self.is_file_done(file):
                print(f"Processing file: {file.name}")
                self.process_file(file)

    def scan(self):
        self.current_files = {
            f.name: File(f) for f in Path(self.watch_dir).glob("*.mkv")
        }
        self.processed_files = self.load_processed_files()

    def on_modified(self, event):
        if event.src_path.endswith(".mkv"):
            # print(f"File '{event.src_path}' has been modified.")
            # print(self.current_files, self.processed_files)
            self.scan()
            file = File(Path(event.src_path))
            if not self.is_file_done(file) and self.is_file_ready(file):
                self.process_file(file)

    def is_file_done(self, file: File):
        current_size = file.get_size()
        if (
            mkv := self.processed_files.get(file.name, None)
        ) and mkv.size == current_size:
            return True

        return False

    def is_file_ready(self, file: File):
        current_size = file.get_size()
        if (
            mkv := self.current_files.get(file.name, None)
        ) and mkv.size == current_size:
            return True

        print(f"File '{file.name}' is not ready yet.")

        return False

    def process_file(self, file: File):
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
                subprocess.run(cmd, check=True)

            updated = self.current_files[file.name]
            updated.mtime = file.get_mtime()
            updated.size = file.get_size()
            updated.processed = True
            self.save_processed_files()
        except subprocess.CalledProcessError as e:
            print(f"Error processing file {file.name}: {e}")

    def load_processed_files(self):
        processed_files = {}
        Path(self.log_file).touch(exist_ok=True)
        with open(self.log_file, "r") as f:
            processed_files = {
                mkv.name: mkv
                for mkv in [(File.from_csv(line, self.watch_dir)) for line in f]
                if mkv.name in self.current_files
            }

            return processed_files

    def save_processed_files(self):
        with open(self.log_file, "w") as f:
            for mkv in [m for m in self.current_files.values() if m.processed]:
                f.write(f"{mkv.name},{mkv.mtime},{mkv.size}\n")

        self.processed_files = deepcopy(self.current_files)


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
        "-t", "--timer", type=int, default=10, help="Number of seconds to wait/loop"
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

    event_handler = ConvertedVideoHandler(watch_dir=path)
    observer = Observer()
    observer.schedule(event_handler, path, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(args.timer)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
