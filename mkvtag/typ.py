from typing import Literal

Status = Literal[
    "new", "done", "processing", "waiting", "failed", "gone", "renamed", "ready"
]
