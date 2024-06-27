import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from deepdiff import DeepDiff
from humanize import naturalsize, naturaltime
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

SLEEP_TIME = 5 if "pytest" in sys.modules else 30
MODIFIED_SAFE_TIME = 30
LOG_FILE_NAME = "mkvtag.json"

Status = Literal["new", "done", "processing", "waiting", "failed", "gone"]


class File:
    def __init__(self, file_path: Path, tagger: "MkvTagger"):
        self.path = file_path
        self._mtime = file_path.stat().st_mtime if file_path.exists() else 0.0
        self._last_mtime = self._mtime
        self._size = file_path.stat().st_size if file_path.exists() else 0
        self._last_size = self._size
        self._status: Status = "new"
        self._failed_count = 0
        self._tagger = tagger

    def __repr__(self):
        return f"File({self.name}, {self.friendly_mtime}, {self.friendly_size}, status={self.status})"

    @property
    def name(self):
        return self.path.name

    @property
    def mtime(self):
        try:
            if self._mtime != self._last_mtime:
                self._last_mtime = self._mtime
            self._mtime = Path(self.path).stat().st_mtime
            return self._mtime
        except FileNotFoundError:
            return 0.0

    @property
    def friendly_mtime(self):
        return naturaltime(datetime.now() - datetime.fromtimestamp(self._mtime))

    @property
    def size_changed_since_last_check(self):
        return self._last_size != self.size

    @property
    def was_recently_modified(self):
        return time.time() - self.mtime < MODIFIED_SAFE_TIME

    @property
    def size(self):
        try:
            if self._size != self._last_size:
                self._last_size = self._size
            self._size = Path(self.path).stat().st_size
            return self._size
        except FileNotFoundError:
            return 0

    @property
    def friendly_size(self):
        from humanize import naturalsize

        return naturalsize(self._size or 0)

    @property
    def status(self) -> Status:
        if self._status:
            return self._status
        self._tagger.scan()
        if not (ref := self._tagger.files.get(self.name)):
            self._status = "gone"
            return self._status

        self._status = ref.status
        return self._status

    @status.setter
    def status(self, value: Status):
        self._failed_count += 1 if value == "failed" else 0
        self._status = value
        self._tagger.files[self.name] = self
        self.save_to_log(self._tagger.log_file)

    @property
    def failed_count(self):
        return self._failed_count

    def fail(self):
        self._failed_count += 1
        self._status = "failed"
        self._tagger.files[self.name] = self
        self.save_to_log(self._tagger.log_file)

    @classmethod
    def from_json(cls, data: dict, *, tagger: "MkvTagger"):
        new = cls(tagger.watch_dir / data["name"], tagger)
        mtime = data["mtime"]
        # convert from ISO 8601 format to timestamp
        try:
            mtime = datetime.fromisoformat(mtime).timestamp()
        except ValueError:
            ...
        new._last_mtime = mtime
        new._mtime = mtime
        new._last_size = data["size"]
        new._size = data["size"]
        new._failed_count = int(data.get("failed_count", 0))
        new._status = data["status"]
        return new

    def to_json(self):
        return {
            "name": self.name,
            "mtime": datetime.fromtimestamp(self.mtime).isoformat(),
            "size": self.size,
            "failed_count": self._failed_count,
            "status": self._status,
        }

    def save_to_log(self, log_file: Path):
        files = {f.name: f.to_json() for f in self._tagger.files.values()}
        with open(log_file, "w") as f:
            # update the log file if the file already exists, otherwise append
            json.dump(files, f, indent=4)

    def __eq__(self, other):
        return self.name == other.name


class MkvTagger(FileSystemEventHandler):
    files: dict[str, File]
    _is_processing = False
    _active_file: str | None = None

    def __init__(self, watch_dir: Path = Path.cwd()):
        self.watch_dir = watch_dir
        self.log_file = self.watch_dir / LOG_FILE_NAME
        self.files = {}

        if not self.watch_dir.exists():
            raise FileNotFoundError(f"Watch dir '{self.watch_dir}' does not exist")

        if not self.log_file.exists():
            self.log_file.touch()

        print("Watching for new files...\n")

        self.files = self.scan(reset=True)

        self.process_dir()

    def process_dir(self):
        for file in self.files.values():
            self.process_file(file)

    def on_modified(self, event):

        if LOG_FILE_NAME in event.src_path:
            # update the files list if the log file is modified
            # if log file matches self.files, skip
            if not DeepDiff(self.files, self.scan(), ignore_order=True):
                return

            self.files.update(self.scan())

        if event.src_path.endswith(".mkv"):
            path = Path(event.src_path)
            # try to get file from self.files
            if not (file := self.files.get(path.name)):
                # if file is not in self.files, add it
                file = File(path, self)
                self.files[file.name] = file
            self.process_file(file)

    def is_active_file(self, file: File):
        return file.name == self._active_file

    def scan(self, reset: bool = False) -> dict[str, "File"]:
        log_file = self.watch_dir / LOG_FILE_NAME
        logged_files = {}
        dir_files = {f.name: File(f, self) for f in Path(self.watch_dir).glob("*.mkv")}
        if not log_file.exists():
            with open(log_file, "w") as f:
                json.dump({}, f, indent=4)
        with open(log_file, "r") as f:
            try:
                file_data = json.load(f)
                # if file data is not an object, raise
                if not isinstance(file_data, dict):
                    raise json.JSONDecodeError(
                        "Invalid JSON data, expected an object.", "", 0
                    )
            except json.JSONDecodeError:
                print("Error decoding JSON data from log file, resetting log file.\n")
                file_data = {}
                # save empty list to log file
                with open(log_file, "w") as f:
                    json.dump({}, f, indent=4)

            logged_files = {
                item["name"]: File.from_json(
                    item, tagger=self
                )  # Assuming a new method `from_json`
                for item in file_data.values()
            }

            # update the status of files that are no longer in the directory
            for name, file in logged_files.items():
                if name not in dir_files.keys():
                    file._status = "gone"

            # add new files from dir_files to logged_files
            new_files = {
                name: file
                for name, file in dir_files.items()
                if name not in logged_files.keys()
            }

            merged = {**logged_files, **new_files}

            if reset:
                for file in merged.values():
                    if file.status not in ["done", "gone"]:
                        # if mtime is older than 1 minute, set status to "new"
                        if time.time() - file.mtime > 60 and file.failed_count < 3:
                            file._status = "new"

            return merged

    def process_file(self, file: File):

        if file.status in ["done", "gone"]:
            return

        if self._is_processing or self.is_active_file(file):
            return

        if file.status == "failed" and file.failed_count >= 3:
            if file.failed_count == 3:
                print(f"File '{file.name}' has already failed 3 times, giving up :(")
                file.fail()
            return

        if file.was_recently_modified or file.size_changed_since_last_check:
            if file.status == "waiting":
                return

            file.status = "waiting"

            if file.size_changed_since_last_check:
                size_diff = file.size - file._last_size
                friendly_size_diff = naturalsize(abs(size_diff))
                if size_diff > 0:
                    print(
                        f"File '{file.name}' has changed size by {friendly_size_diff}, skipping for now..."
                    )
                time.sleep(SLEEP_TIME)
                if file.size_changed_since_last_check:
                    file.save_to_log(self.log_file)
                    return

            else:
                time_since_modified_friendly = naturaltime(
                    datetime.now() - datetime.fromtimestamp(file.mtime)
                )
                if time_since_modified_friendly == "now":
                    time_since_modified_friendly = "a second ago"
                print(
                    f"File '{file.name}' was last modified {time_since_modified_friendly}, skipping for now..."
                )
                time.sleep(SLEEP_TIME)
                if file.was_recently_modified:
                    file.save_to_log(self.log_file)
                    return

        if file.status == "failed":
            print(f"File '{file.name}' failed to process, retrying...")
            file.status = "new"

        print(f"Processing file: {file.name}")
        self._is_processing = True
        self._active_file = file.name
        file.status = "processing"

        try:
            if file.name == "sample_1280x720_failed.mkv":
                raise subprocess.CalledProcessError(
                    1,
                    "mkvpropedit --add-track-statistics-tags [test] failure (intentional)",
                )
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
                res = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                if res.returncode != 0:
                    raise subprocess.CalledProcessError(res.returncode, res.args)
                print(f"Done\n")
                file.status = "done"

        except subprocess.CalledProcessError as e:
            msg = f"Error processing file: {file.name}"
            if proc_error := (e.stderr.decode("utf-8") if e and e.stderr else ""):
                print(f"{msg}:")
                print(proc_error)
            else:
                print(f"{msg}\n")
            file.fail()
        finally:
            self._is_processing = False
            self._active_file = None


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
