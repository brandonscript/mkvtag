from typing import Any


def coerce_to_bool(v: Any, strict: bool = False) -> bool:
    """Coerces a value to a boolean. If strict is True, will raise
    an error if the value is not explicitly false or true, otherwise
    will return True if the value is truthy and False otherwise."""
    if is_maybe_true(v):
        return True
    elif is_maybe_false(v) or not strict:
        return False
    else:
        raise ValueError(f"Cannot parse boolean from value: {v}")


def is_maybe_true(v: Any) -> bool:
    return str(v).lower() in ["true", "t", "yes", "y"]


def is_maybe_false(v: Any) -> bool:
    return str(v).lower() in ["false", "f", "no", "n"]
