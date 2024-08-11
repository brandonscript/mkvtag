import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from deepdiff import DeepDiff
from humanize import naturalsize, naturaltime
from watchdog.events import FileSystemEventHandler

from mkvtag.constants import LOG_FILE_NAME, SLEEP_TIME
from mkvtag.file import File


class MkvTagger(FileSystemEventHandler):
    files: dict[str, File]
    _is_processing = False
    _active_file: str | None = None

    def __init__(
        self,
        watch_dir: Path = Path.cwd(),
        log_file: Path | None = None,
        rename_exp: str | None = None,
    ):
        self.watch_dir = watch_dir
        self.log_file = (
            (self.watch_dir / LOG_FILE_NAME)
            if not log_file
            else (
                (self.watch_dir / log_file)
                if log_file.parent.is_relative_to(self.watch_dir)
                else (log_file if log_file.is_absolute() else Path.cwd() / log_file)
            )
        )
        # if log file does not exist, or if it is empty, write an empty object
        if self.log_file_empty_or_missing:
            with open(self.log_file, "w") as f:
                f.write("{}")

        self.rename_exp = rename_exp

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
            scan = self.scan()
            if not DeepDiff(self.files, scan, ignore_order=True):
                return

            self.files.update(scan)

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

    @property
    def log_file_empty_or_missing(self) -> bool:
        return (
            not self.log_file.exists()
            or self.log_file.stat().st_size == 0
            or self.log_file.read_text().strip() == ""
        )

    @property
    def logged_files(self) -> dict[str, File]:
        logged_files = {}
        if self.log_file_empty_or_missing:
            with open(self.log_file, "w") as f:
                f.write("{}")
        with open(self.log_file, "r") as f:
            try:
                file_data = json.load(f)
                # if file data is not an object, raise
                if not isinstance(file_data, dict):
                    raise json.JSONDecodeError(
                        f"Invalid JSON data in {self.log_file} – expected an object.",
                        "",
                        0,
                    )
            except json.JSONDecodeError as e:
                raise json.JSONDecodeError(
                    f"Error decoding JSON data from log file - delete {self.log_file} or ensure it contains a valid JSON object ('{{}}').",
                    e.doc,
                    e.pos,
                ) from e

            logged_files = {
                item["name"]: File.from_json(item, tagger=self, **item)
                for item in file_data.values()
            }

        return logged_files

    def _get_dir_files(self) -> dict[str, "File"]:
        return {f.name: File(f, self) for f in Path(self.watch_dir).glob("*.mkv")}

    def scan(self, reset: bool = False) -> dict[str, "File"]:

        dir_files = self._get_dir_files()

        if self.rename_exp:
            for file in dir_files.values():
                file.rename()
            dir_files = self._get_dir_files()

        # add new files from dir_files to logged_files
        new_files = {
            name: file
            for name, file in dir_files.items()
            if name not in self.logged_files.keys()
            or self.logged_files[name].status == "gone"
        }

        merged = {**self.logged_files, **new_files}

        # set files that don't exist in the directory to "gone"
        for name, file in merged.items():
            if name not in dir_files.keys():
                file._status = "gone"

        if reset:
            for file in merged.values():
                if file.status not in ["done", "gone"] and file.path.exists():
                    # if mtime is older than 1 minute, set status to "new"
                    if time.time() - file.mtime > 60 and file.failed_count < 3:
                        file._status = "new"

        with open(self.log_file, "w") as f:
            # update the log file if the file already exists, otherwise append
            # merge the logged files with the new files
            json.dump({f.name: f.to_json() for f in merged.values()}, f, indent=2)
        return merged

    def process_file(self, file: File):

        if file.status in ["done"]:
            return

        if file.status == "gone":
            if not file.path.exists():
                return
            else:
                file.status = "new"

        if self._is_processing or self.is_active_file(file):
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
                    file.save_to_log()
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
                    file.save_to_log()
                    return

        if file.status == "failed":
            if file.failed_count >= 3:
                if file.failed_count == 3:
                    print(
                        f"File '{file.name}' has already failed 3 times, giving up :("
                    )
                    file.fail()
                return
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
