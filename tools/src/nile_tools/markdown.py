"""Find and rewrite the local image links in a guide. Pure: text in, text out, no files."""

import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "Ref",
    "is_local",
    "local_image_paths",
    "macro_lines",
    "resolve",
    "rewrite_images",
    "scan",
]

Kind = Literal["image", "ref-image", "img-tag", "link"]

# A path that starts with one of these is not a file in the course folder.
_NOT_LOCAL = ("http:", "https:", "data:", "/", "#")

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`)([^\n]+?)(?<!`)\1(?!`)")
_TARGET = r"(?P<target><[^>\n]*>|[^\s)]*)"
_IMAGE = re.compile(rf"!\[(?P<alt>[^\]]*)\]\(\s*{_TARGET}(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_REF_IMAGE = re.compile(r"!\[[^\]]*\]\[[^\]]*\]")
_LINK = re.compile(rf"(?<!!)\[[^\]]*\]\(\s*{_TARGET}[^)]*\)")
_IMG_TAG = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']?(?P<target>[^\"'\s>]+)", re.IGNORECASE)


@dataclass(frozen=True)
class Ref:
    """One image, link or `<img>` found outside code. `start`/`end` span the path in the text."""

    kind: Kind
    target: str
    alt: str
    line: int
    start: int
    end: int


def is_local(target: str) -> bool:
    """True when a link target points at a file in the course folder."""
    return not target.lower().startswith(_NOT_LOCAL)


def _code_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    pos = 0
    fence: tuple[str, int, int] | None = None  # character, length, start
    for line in text.splitlines(keepends=True):
        m = _FENCE.match(line)
        if fence is None:
            if m:
                fence = (m.group(1)[0], len(m.group(1)), pos)
        elif (
            m
            and m.group(1)[0] == fence[0]
            and len(m.group(1)) >= fence[1]
            and line.strip() == m.group(1)  # a closing fence has no text after it
        ):
            ranges.append((fence[2], pos + len(line)))
            fence = None
        pos += len(line)
    if fence is not None:
        ranges.append((fence[2], len(text)))  # an unclosed fence runs to the end
    fenced = list(ranges)
    for m in _INLINE_CODE.finditer(text):
        if not any(a <= m.start() < b for a, b in fenced):
            ranges.append(m.span())
    return ranges


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def scan(text: str) -> list[Ref]:
    """List every image, link and `<img>` outside code, in text order."""
    code = _code_ranges(text)
    refs: list[Ref] = []

    def outside(offset: int) -> bool:
        return not any(a <= offset < b for a, b in code)

    def add(kind: Kind, m: re.Match[str], alt: str = "") -> None:
        if not outside(m.start()):
            return
        start, end = m.span("target") if "target" in m.groupdict() else m.span()
        target = text[start:end]
        if target.startswith("<") and target.endswith(">") and len(target) >= 2:
            start, end, target = start + 1, end - 1, target[1:-1]
        refs.append(Ref(kind, target, alt, _line(text, m.start()), start, end))

    for m in _IMAGE.finditer(text):
        add("image", m, m.group("alt"))
    for m in _REF_IMAGE.finditer(text):
        add("ref-image", m)
    for m in _LINK.finditer(text):
        add("link", m)
    for m in _IMG_TAG.finditer(text):
        add("img-tag", m)
    return sorted(refs, key=lambda r: r.start)


def macro_lines(text: str) -> list[int]:
    """Return the line number of every `{{` in the text (code included)."""
    return [i for i, line in enumerate(text.splitlines(), 1) if "{{" in line]


def resolve(base_dir: str, target: str) -> str | None:
    """Return the course relative path a target means, or None if it leaves the folder."""
    path = posixpath.normpath(posixpath.join(base_dir, target))
    return None if path == ".." or path.startswith("../") or path.startswith("/") else path


def local_image_paths(text: str, base_dir: str) -> list[str]:
    """List the resolved course relative path of every local `![alt](path)` image, in order."""
    paths = [
        resolve(base_dir, r.target) for r in scan(text) if r.kind == "image" and is_local(r.target)
    ]
    return [p for p in paths if p is not None]


def rewrite_images(text: str, base_dir: str, urls: Mapping[str, str]) -> str:
    """Replace the path of each local image with its URL; code and unknown images stay."""
    out: list[str] = []
    last = 0
    for r in scan(text):
        if r.kind != "image" or not is_local(r.target):
            continue
        path = resolve(base_dir, r.target)
        if path is None or path not in urls:
            continue
        out += [text[last : r.start], urls[path]]
        last = r.end
    out.append(text[last:])
    return "".join(out)
