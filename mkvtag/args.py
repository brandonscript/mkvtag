import os
from pathlib import Path

from mkvtag.constants import SLEEP_TIME
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
            help="Number of seconds to wait/loop",
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
