import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from threading import Lock
from typing import Any

from deepdiff import DeepDiff
from humanize import naturalsize
from watchdog.events import FileModifiedEvent, FileSystemEvent, FileSystemEventHandler

from mkvtag.args import MkvTagArgs
from mkvtag.constants import LOG_FILE_NAME
from mkvtag.file import File

LOG_FILE_LOCK = Lock()

from watchdog.observers.api import BaseObserver


class MkvTagger(FileSystemEventHandler):
    files: dict[str, File]
    _is_processing = False
    _active_file: str | None = None
    _error_state_timestamp: float = 0
    _log_file_error_count = 0

    def __init__(
        self,
        watch_dir: Path = Path.cwd(),
        args=MkvTagArgs(),
    ):
        self._last_title_printed = ""
        self.watch_dir = watch_dir
        self.rename_exp = args.clean
        self.exc = args.exc
        self._args = args
        self.log_file = (
            (self.watch_dir / LOG_FILE_NAME)
            if not args.log
            else (
                (self.watch_dir / args.log)
                if args.log.parent.is_relative_to(self.watch_dir)
                else (args.log if args.log.is_absolute() else Path.cwd() / args.log)
            )
        )
        if not self.watch_dir.exists():
            raise FileNotFoundError(f"Watch dir '{self.watch_dir}' does not exist")

        self._log_data: dict[str, dict[str, Any]] = None  # type: ignore
        self.files = {}

        print("Watching for new files...\n")

        self.refresh()

    def refresh(self):
        if self.error_state:
            return

        self.read_log()
        scan = self.scan()
        if not DeepDiff(self.files, scan, ignore_order=True):  # type: ignore
            return

        self.files = scan

    def on_created(self, event: FileSystemEvent) -> None:
        self.refresh()

    def on_closed(self, event: FileSystemEvent) -> None:
        self.refresh()
        if event.src_path.endswith(".mkv"):
            path = Path(event.src_path)
            # try to get file from self.files
            if not (file := self.files.get(path.name)):
                # if file is not in self.files, add it
                file = File(path, self)
                self.files[file.name] = file
            self.process_file(file)

    def on_modified(self, event):
        if event.src_path.endswith(".mkv"):
            path = Path(event.src_path)
            # try to get file from self.files
            if not (file := self.files.get(path.name)):
                # if file is not in self.files, add it
                file = File(path, self)
                self.files[file.name] = file
            self.process_file(file)
        elif event.src_path.endswith(LOG_FILE_NAME):
            self.read_log()

    def on_deleted(self, event):
        if event.src_path.endswith(".mkv"):
            path = Path(event.src_path)
            # try to get file from self.files
            if not (file := self.files.get(path.name)):
                # if file is not in self.files, add it
                file = File(path, self)
                self.files[file.name] = file
                file.status = "gone"
            self.process_file(file)

    def queue_files(self, observer: BaseObserver) -> None:
        for mkv in Path(self.watch_dir).glob("*.mkv"):
            # if the file is not in self.files and done, add to queue
            if not (file := self.files.get(mkv.name)) or not file.status == "done":
                # print("(Re-)queueing", mkv.name, f"({file.status if file else "new"})")
                if emitter := next(iter(observer.emitters)):
                    emitter.queue_event(
                        event=FileModifiedEvent(str(mkv), is_synthetic=True),
                    )

    def is_active_file(self, file: File):
        return file.name == self._active_file

    @property
    def error_state(self) -> bool:
        time_since_last_err = time.time() - self._error_state_timestamp
        error_wait_time = self._args.timer / (2.5 if "pytest" in sys.modules else 1)

        if time_since_last_err < error_wait_time:
            return True

        self._error_state_timestamp = 0
        return False

    def handle_json_error(
        self, msg: str, err: Exception | json.JSONDecodeError, *, autofix: bool = True
    ):
        self._error_state_timestamp = time.time()
        msg = msg if not autofix else f"{msg} (re-creating)"
        print(msg, "\n")
        if autofix:
            self._log_data = {}
            self.log_file.unlink(missing_ok=True)
            self.read_log()

        if self.exc:
            raise err

    @property
    def log_file_empty_or_missing(self) -> bool:
        return (
            not self.log_file.exists()
            or self.log_file.stat().st_size == 0
            or self.log_file.read_text().strip() == ""
        )

    def read_log(self):

        global LOG_FILE_LOCK

        if self.error_state:
            self._log_file_error_count = 0
            return

        file_data: dict[str, dict[str, Any]] = {}
        if not self.log_file.exists():
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            while LOG_FILE_LOCK.locked():
                time.sleep(0.1)
            with LOG_FILE_LOCK:
                with open(self.log_file, "w") as f:
                    f.write("{}")
            self._log_data = {}
            return

        while LOG_FILE_LOCK.locked():
            time.sleep(0.1)
        with LOG_FILE_LOCK:
            with open(self.log_file, "r") as f:
                try:
                    raw_data = f.read()
                    file_data = json.loads(raw_data)
                    if not isinstance(file_data, dict):
                        raise json.JSONDecodeError(
                            f"Expected JSON object ('{{}}'), got {type(file_data).__name__}",
                            "",
                            0,
                        )
                    self._log_data = file_data
                except json.JSONDecodeError as e:
                    self.handle_json_error(
                        f"Log file is malformed - '{self.log_file}'",
                        e,
                        autofix=True,
                    )
                    return

    @property
    def logged_files(self) -> dict[str, File]:
        if self.error_state:
            return {}

        log_data = self._log_data or {}

        return {
            item["name"]: File.from_json(item, tagger=self, **item)
            for item in log_data.values()
        }

    def _get_dir_files(self) -> dict[str, "File"]:
        return {f.name: File(f, self) for f in Path(self.watch_dir).glob("*.mkv")}

    def scan(self, reset: bool = False) -> dict[str, "File"]:
        global LOG_FILE_LOCK

        if self.error_state:
            return {}

        dir_files = self._get_dir_files()

        # add new files from dir_files to logged_files
        new_files = {
            name: file
            for name, file in dir_files.items()
            if name not in self.logged_files.keys()
        }

        merged = {**self.logged_files, **new_files}

        # set files that don't exist in the directory to "gone"
        for name, file in merged.items():
            if name not in dir_files.keys():
                file._status = "gone"
            if name in self.files.keys() and self.files[name].status in [
                "done",
                "gone",
            ]:
                file._status = self.files[name].status

        # if any record in data is "gone" and mtime is older than 1 day, remove it
        def is_too_old(file: File) -> bool:
            too_old = 120 if "pytest" in sys.modules else 86400
            if file_is_too_old := (
                file.status == "gone" and time.time() - file.mtime > too_old
            ):
                # print(f"'{file.name}' is too old, removing from log...")
                ...
            return file_is_too_old

        merged = {name: file for name, file in merged.items() if not is_too_old(file)}

        if reset:
            for file in merged.values():
                if file.status not in ["done", "gone"] and file.path.exists():
                    # if mtime is older than 1 minute, set status to "new"
                    if time.time() - file.mtime > 60 and file.failed_count < 3:
                        file._status = "new"

        while LOG_FILE_LOCK.locked():
            time.sleep(0.1)
        with LOG_FILE_LOCK:
            data = {f.name: f.to_json() for f in merged.values()}
            with open(self.log_file, "w") as wf:
                try:
                    json.dump(data, wf, indent=2, ensure_ascii=False)
                except Exception as e:
                    self.handle_json_error(
                        f"Error (scan) writing to log file '{self.log_file}'",
                        e,
                        autofix=False,
                    )
        self.read_log()
        return merged

    def check_file_bitrate(self, file: File):
        # Runs `mkvinfo -t {file} | awk '/\+ Track/ {track=1} /Track type: video/ {video=track} video && /Name: BPS/ {getline; print $NF; exit}' | xargs`
        # and returns the bitrate of the video track in the file
        try:

            cmd = [
                "mkvinfo",
                "-t",
                str(file.path),
                "|",
                "awk",
                "'/\\+ Track/ {track=1} /Track type: video/ {video=track} video && /Name: BPS/ {getline; print $NF; exit}'",
                "|",
                "xargs",
            ]
            res = subprocess.run(
                " ".join(cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
            )
            return res.stdout.decode("utf-8").strip()
        except subprocess.CalledProcessError as _e:
            # bitrate checking might not be available on all systems, so just return an empty string
            return ""

    def rename_file(self, file: File):
        if self.rename_exp and file.status == "done":
            [orig, new] = file.rename() or [None, None]
            if not orig or not new:
                return
            self.files[new] = self.files.pop(orig)
            self._log_data.pop(orig)
            self._log_data[new] = file.to_json()
            file.save_to_log()
            self.read_log()

    def process_file(self, file: File):

        def print_title():
            if file.name == self._last_title_printed:
                return
            print(f"\n'{file.name}'")
            self._last_title_printed = file.name

        # if file is missing, set it to "gone" and return
        if not file.path.exists():
            file.status = "gone"
            return

        if self.error_state:
            return

        if file.status in ["done"] or file.failed_count >= 3:
            return

        if (
            self._args.precheck
            and (bitrate := self.check_file_bitrate(file))
            and bitrate != ""
        ):
            if not file.status == "done":
                bitrate_human = naturalsize(int(bitrate))
                print_title()
                print(f"Already has bitrate info ({bitrate_human}/s)")
            file.status = "done"
            self.rename_file(file)
            return

        if (
            file.name in self.logged_files.keys()
            and (logged_file := self.logged_files[file.name])
            and logged_file.status
            in [
                "done",
                "gone",
            ]
        ):
            file._status = logged_file.status
            return

        if file.status == "gone":
            if not file.path.exists():
                return
            else:
                file.status = "new"

        if self._is_processing or self.is_active_file(file):
            return

        if file.status == "waiting":
            time.sleep(0.1)
            if file.was_recently_modified or file.size_changed_since_last_check:
                return
            else:
                file.status = "ready"
        elif file.was_recently_modified or file.size_changed_since_last_check:
            print_title()
            print(f"New (waiting)")
            file.status = "waiting"
            return

        if file.status == "failed":
            if file.failed_count >= 3:
                return
            print_title()
            print(f"Processing failed, retrying...")
            file.status = "ready"

        else:
            print_title()
            print(f"Processing...")
        self._is_processing = True
        self._active_file = file.name
        file.status = "processing"

        try:
            if "pytest" in sys.modules and file.name == "sample_1280x720_failed.mkv":
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
                print_title()
                file.status = "done"
                self.rename_file(file)
                print(f"Done")

        except subprocess.CalledProcessError as e:
            file.fail()
            print_title()
            print(
                "Failed",
                f"({file.failed_count}x){", giving up :(" if file.failed_count == 3 else ''}",
            )
            if proc_error := (e.stderr.decode("utf-8") if e and e.stderr else ""):
                print(proc_error)
        finally:
            self._is_processing = False
            self._active_file = None
