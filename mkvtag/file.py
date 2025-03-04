import json
import re
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from humanize import naturaltime

from mkvtag.typ import Status

if TYPE_CHECKING:
    from mkvtag.tagger import MkvTagger


class File:

    def __init__(self, file_path: Path, tagger: "MkvTagger", **kwargs):

        self.path = file_path
        self.original_path = file_path
        underscored = {
            f"_{k}": v
            for k, v in kwargs.items()
            if k
            in [
                "mtime",
                "size",
                "last_mtime",
                "last_size",
                "failed_count",
                "status",
                "tagger",
            ]
        }
        self.__dict__.update({k: v for k, v in underscored.items()})
        if not "_mtime" in underscored:
            try:
                self._mtime = file_path.stat().st_mtime
            except FileNotFoundError:
                self._mtime = 0.0
        if not "_last_mtime" in underscored:
            self._last_mtime = self._mtime
        if not "_size" in underscored:
            try:
                self._size = file_path.stat().st_size
            except FileNotFoundError:
                self._size = 0
        if not "_last_size" in underscored:
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
    def mtime(self) -> float:
        try:
            if self._mtime != self._last_mtime:
                self._last_mtime = self._mtime
            self._mtime = Path(self.path).stat().st_mtime
            return self._mtime
        except FileNotFoundError:
            return self._mtime or self._last_mtime or 0.0

    @property
    def friendly_mtime(self):
        return naturaltime(
            datetime.now() - datetime.fromtimestamp(self._mtime or self._last_mtime)
        )

    @property
    def size_changed_since_last_check(self):
        return self._last_size != self.size

    @property
    def was_recently_modified(self):
        return time.time() - self.mtime < self._tagger._args.wait

    @property
    def size(self):
        try:
            if self._size != self._last_size:
                self._last_size = self._size
            self._size = Path(self.path).stat().st_size
            return self._size
        except FileNotFoundError:
            return self._size or self._last_size or 0

    @property
    def friendly_size(self):
        from humanize import naturalsize

        return naturalsize(self._size or self._last_size or 0)

    @property
    def clean_name(self):
        if not self._tagger.rename_exp:
            return self.name
        exp = re.compile(self._tagger.rename_exp.strip(), re.IGNORECASE)
        return exp.sub("", self.name)

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
        self._tagger.read_log()
        if logged_file := self._tagger.logged_files.get(self.name, None):
            logged_status = logged_file.status
            # We don't want to go backwards in the state machine, reject the change if the following conditions are met
            reject_because_done_or_gone = logged_status in [
                "done",
                "gone",
            ] and value not in ["new"]
            reject_because_waiting = logged_status == "waiting" and value not in [
                "done",
                "ready",
                "processing",
            ]
            reject_because_processing = logged_status == "processing" and value not in [
                "done",
                "ready",
                "failed",
            ]
            reject_because_failed = logged_status == "failed" and value not in [
                "new",
                "ready",
            ]
            if (
                reject_because_done_or_gone
                or reject_because_waiting
                or reject_because_processing
                or reject_because_failed
            ):
                value = logged_status
        if value == "failed":
            self._failed_count += 1
        self._status = value
        self._tagger.files[self.name] = self
        self._tagger._log_data[self.name] = self.to_json()
        self.save_to_log()

    @property
    def failed_count(self):
        return self._failed_count

    def fail(self):
        self.status = "failed"

    def rename(self, new_name: str | None = None):
        """Rename the file to a new name. If no new name is provided, the file will be renamed to the cleaned name.

        Args:
            new_name (str, optional): The new name for the file. Defaults to None.

        Returns:
            tuple[str, str]: [The original name, the new name] if the file was renamed, otherwise None
        """

        # if the file is gone or waiting, don't rename
        if (
            self.status == "gone"
            or not self.status == "done"
            or not self._tagger.rename_exp
        ):
            return

        orig_name = self.name
        new_path = self.path.with_name(new_name or self.clean_name)
        new_name = new_path.name
        # if the new name is the same as the old name, don't rename
        if new_path == self.path:
            return None
        self.path.rename(new_path)
        self.path = new_path
        print(f"Renaming:\n × | '{orig_name}'\n → | '{self.name}'")

        self._tagger.files[new_name] = self._tagger.files.pop(orig_name)
        self._tagger._log_data.pop(orig_name)
        self._tagger._log_data[new_name] = self.to_json()
        self.save_to_log()
        self._tagger.read_log()

    @classmethod
    def from_json(cls, data: dict, *, tagger: "MkvTagger", **kwargs):
        new = cls(tagger.watch_dir / data["name"], tagger, **kwargs)
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

    def save_to_log(self):
        from mkvtag.tagger import LOG_FILE_LOCK

        logged_files = deepcopy(self._tagger.logged_files)
        # update the file in the logged files or add it if it doesn't exist
        logged_files[self.name] = deepcopy(self)

        # if self.original_path != self.path, delete the old file from the log
        if self.original_path != self.path:
            logged_files.pop(self.original_path.name, None)

        data = {f.name: f.to_json() for f in logged_files.values()}

        while LOG_FILE_LOCK.locked():
            time.sleep(0.1)
        with LOG_FILE_LOCK:
            try:
                with open(self._tagger.log_file, "w") as wf:
                    json.dump(data, wf, indent=2, ensure_ascii=False)
            except json.JSONDecodeError as e:
                self._tagger.handle_json_error(
                    f"Error (save_to_log) writing to log file '{self._tagger.log_file}'",
                    e,
                    autofix=False,
                )
                return {}

    def __eq__(self, other):
        return self.name == other.name
