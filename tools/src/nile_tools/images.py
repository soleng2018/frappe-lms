"""Rules for course images: allowed types, size, name, and the name an upload gets in the LMS."""

import hashlib
import re

__all__ = ["EXTENSIONS", "MAX_BYTES", "file_problems", "path_problems", "stored_name"]

EXTENSIONS = ("png", "jpg", "jpeg", "gif", "webp")
MAX_BYTES = 5_000_000  # 5 MB, where 1 MB is 1,000,000 bytes
_NAME_OK = re.compile(r"[a-z0-9._-]+")


def _magic_ok(ext: str, data: bytes) -> bool:
    if ext == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in ("jpg", "jpeg"):
        return data.startswith(b"\xff\xd8\xff")
    if ext == "gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    return data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def path_problems(target: str) -> list[str]:
    """Name what is wrong with the written path itself (query, fragment, percent encoding)."""
    return [f"image path {target!r} must not contain {ch!r}" for ch in "?#%" if ch in target]


def file_problems(name: str, data: bytes) -> list[str]:
    """Name what is wrong with an image file: its name, type, first bytes and size."""
    problems = []
    if not _NAME_OK.fullmatch(name):
        problems.append(f"image file name {name!r} may only use a-z, 0-9, dot, dash and underscore")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in EXTENSIONS:
        problems.append(f"image {name!r} must be {', '.join(EXTENSIONS)}, not {ext or 'no type'!r}")
    elif not _magic_ok(ext, data):
        problems.append(f"image {name!r} is not really a {ext} file (its first bytes differ)")
    if len(data) > MAX_BYTES:
        problems.append(f"image {name!r} is {len(data)} bytes, the limit is {MAX_BYTES}")
    return problems


def stored_name(course_key: str, data: bytes, file_name: str) -> str:
    """Return the LMS file name: course key, first 12 hex of the sha256, the original name."""
    return f"{course_key}-{hashlib.sha256(data).hexdigest()[:12]}-{file_name}"
