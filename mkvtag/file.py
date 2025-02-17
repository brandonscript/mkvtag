import json
import re
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from humanize import naturaltime

from mkvtag.constants import MODIFIED_SAFE_TIME
from mkvtag.typ import Status

if TYPE_CHECKING:
    from mkvtag.tagger import MkvTagger


class File:

    def __init__(self, file_path: Path, tagger: "MkvTagger", **kwargs):

        self.path = file_path
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
    def mtime(self):
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
        return time.time() - self.mtime < MODIFIED_SAFE_TIME

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
        self._failed_count += 1 if value == "failed" else 0
        self._status = value
        self._tagger.files[self.name] = self
        self.save_to_log()

    @property
    def failed_count(self):
        return self._failed_count

    def fail(self):
        self._failed_count += 1
        self._status = "failed"
        self._tagger.files[self.name] = self
        self.save_to_log()

    def rename(self, new_name: str | None = None):

        # if the file is gone or waiting, don't rename
        if self.status in ["gone", "waiting"]:
            return

        old_path = self.path
        new_path = self.path.with_name(new_name or self.clean_name)
        # if the new name is the same as the old name, don't rename
        if new_path == self.path:
            return
        self.path.rename(new_path)
        self.path = new_path
        # update the file in the tagger
        self._tagger.files[self.name] = self
        # rename the file in the log
        with open(self._tagger.log_file, "w") as f:
            # find the old_path in the log and rename it
            logged_files = json.load(f)
            logged_files[new_path.name] = logged_files.pop(old_path.name)
            json.dump(logged_files, f, indent=2)

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
        logged_files = deepcopy(self._tagger.logged_files)
        # update the file in the logged files or add it if it doesn't exist
        logged_files[self.name] = self
        with open(self._tagger.log_file, "w") as f:
            json.dump({f.name: f.to_json() for f in logged_files.values()}, f, indent=2)

    def __eq__(self, other):
        return self.name == other.name
