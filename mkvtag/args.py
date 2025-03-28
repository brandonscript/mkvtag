import os
from pathlib import Path

from mkvtag.constants import MODIFIED_SAFE_TIME, SLEEP_TIME
from mkvtag.utils import coerce_to_bool


class Args:
    @staticmethod
    def path(parser):
        parser.add_argument(
            "path", nargs="?", default=os.getcwd(), help="Directory to watch"
        )

    @staticmethod
    def log(parser):
        parser.add_argument(
            "--log",
            action="store",
            type=Path,
            default=os.getenv("MKVTAG_LOGFILE", None),
        )

    @staticmethod
    def timer(parser):
        parser.add_argument(
            "-t",
            "--timer",
            type=int,
            default=os.getenv("MKVTAG_TIMER", SLEEP_TIME),
            help="Seconds to wait before each loop",
        )

    @staticmethod
    def wait(parser):
        parser.add_argument(
            "-w",
            "--wait",
            type=int,
            default=os.getenv("MKVTAG_WAIT", MODIFIED_SAFE_TIME),
            help="Seconds to wait after a file is modified before processing",
        )

    @staticmethod
    def loops(parser):
        parser.add_argument(
            "-l",
            "--loops",
            type=int,
            default=os.getenv("MKVTAG_LOOPS", -1),
            help="Number of loops to run before exiting (default: -1 to run indefinitely)",
        )

    @staticmethod
    def clean(parser):
        parser.add_argument(
            "-x",
            "--clean",
            action="store",
            type=str,
            default=os.getenv("MKVTAG_CLEAN", None),
            help="A case-insensitive regular expression that all matching substrings will be stripped from the filename",
        )

    @staticmethod
    def precheck(parser):
        parser.add_argument(
            "-c",
            "--precheck",
            action="store_true",
            default=coerce_to_bool(os.getenv("MKVTAG_PRECHECK", False)),
            help="If passed, mkvtag will check files using `mkvinfo` before processing for existing bitrate info",
        )

    @staticmethod
    def exc(parser):
        parser.add_argument(
            "-e",
            "--exc",
            action="store",
            nargs="?",
            type=lambda x: coerce_to_bool(x),
            default=coerce_to_bool(os.getenv("MKVTAG_EXC", False)),
            help="If passed, then the program will raise on exceptions (true), otherwise suppress them (false)",
        )


class MkvTagArgs:
    def __init__(self):
        self.path: str = ""
        self.log: Path | None = None
        self.timer: int = SLEEP_TIME
        self.wait: int = MODIFIED_SAFE_TIME
        self.loops = -1
        self.clean: str | None = None
        self.precheck: bool = False
        self.exc: bool = False
