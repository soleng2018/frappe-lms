"""Read `content/<course-key>/` folders into the frozen content model, collecting every problem."""

import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from nile_tools import images, markdown
from nile_tools.content import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_PASSING_PERCENTAGE,
    Block,
    Chapter,
    Course,
    Image,
    Lesson,
    Option,
    Problem,
    Question,
    Quiz,
    QuizBlock,
    TextBlock,
    VideoBlock,
)
from nile_tools.coursecheck import COURSE_FILE, check_across, check_course

__all__ = [
    "COURSE_FILE",
    "Catalog",
    "ContentError",
    "load_catalog",
    "load_course",
    "read_course",
]

FORMAT = 1
_KEY_RULE = re.compile(r"[a-z0-9][a-z0-9-]*")
_BLOCK_KEYS = ("text", "video", "quiz")


class ContentError(Exception):
    """A course cannot be turned into a sound course; `problems` lists every reason."""

    def __init__(self, problems: tuple[Problem, ...]) -> None:
        super().__init__("\n".join(p.line() for p in problems))
        self.problems = problems


@dataclass(frozen=True)
class Catalog:
    """Every course folder under `content/`: the loaded course (None if unreadable) and problems."""

    courses: Mapping[str, Course | None]
    problems: tuple[Problem, ...]

    def blocked(self) -> dict[str, tuple[Problem, ...]]:
        """Map each folder with an error (not a warning) to its errors."""
        out: dict[str, list[Problem]] = {}
        for p in self.problems:
            if p.course in self.courses and not p.warning:
                out.setdefault(p.course, []).append(p)
        return {k: tuple(v) for k, v in out.items()}

    def ready(self) -> dict[str, Course]:
        """The courses with no problem of their own and no clash, in folder order."""
        blocked = self.blocked()
        return {k: c for k, c in self.courses.items() if c is not None and k not in blocked}


class _Reader:
    """Collects problems while reading, so every one is reported at once."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.root = folder.resolve()
        self.name = folder.name
        self.problems: list[Problem] = []
        self.file = COURSE_FILE
        self._images: dict[str, Image] = {}
        self._guides: dict[str, str | None] = {}
        self.used_guides: set[str] = set()

    def problem(self, where: str, message: str, file: str | None = None) -> None:
        self.problems.append(Problem(self.name, file or self.file, where, message))

    def mapping(self, node: object, where: str) -> Mapping[str, Any]:
        if isinstance(node, Mapping):
            return node
        self.problem(where, "must be a mapping")
        return {}

    def items(self, node: object, where: str) -> list[object]:
        if node is None:
            return []
        if isinstance(node, list):
            return node
        self.problem(where, "must be a list")
        return []

    def text(
        self, node: Mapping[str, Any], field: str, where: str, *, required: bool = True
    ) -> str:
        value = node.get(field)
        if value is None and not required:
            return ""
        if not isinstance(value, str):
            # YAML reads `no` as false and 12345678901 as a number, so say what was found.
            self.problem(
                _join(where, field), f"must be text, found {type(value).__name__} {value!r}"
            )
            return ""
        return value

    def number(self, node: Mapping[str, Any], field: str, default: int, where: str) -> int:
        value = node.get(field, default)
        if isinstance(value, bool) or not isinstance(value, int):
            self.problem(_join(where, field), f"must be a whole number, found {value!r}")
            return default
        return value

    # ---- files inside the course folder

    def inside(self, name: str, where: str, file: str | None = None) -> Path | None:
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            self.problem(where, f"{name!r} points outside the course folder", file)
            return None
        return path

    def guide(self, name: str, where: str) -> str | None:
        """Read a guide once; check its images and macros; return its text or None."""
        key = posixpath.normpath(name)
        if key in self._guides:
            return self._guides[key]
        self._guides[key] = None
        path = self.inside(name, where)
        if path is None:
            return None
        if not path.is_file():
            self.problem(where, f"the file {name!r} does not exist")
            return None
        try:
            md = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            self.problem(where, f"{name!r} cannot be read as UTF-8 text: {e}")
            return None
        if not md.strip():
            self.problem(where, f"the file {name!r} is empty")
        self.used_guides.add(key)
        self._guides[key] = md
        self._guide_checks(key, md)
        return md

    def _guide_checks(self, file: str, md: str) -> None:
        for line in markdown.macro_lines(md):
            self.problem(
                f"line {line}",
                "{{ starts a macro in the LMS, so it is not allowed in a guide",
                file,
            )
        base = posixpath.dirname(file)
        for ref in markdown.scan(md):
            where = f"line {ref.line}"
            local = markdown.is_local(ref.target)
            if ref.kind == "ref-image":
                self.problem(
                    where, "reference style images are not supported, use ![alt](path)", file
                )
            elif ref.kind == "img-tag" and local:
                self.problem(where, "a local <img> is not supported, use ![alt](path)", file)
            elif ref.kind == "link" and local:
                self.problem(
                    where, f"a local link to {ref.target!r} is not supported, only images", file
                )
            elif ref.kind == "image" and local:
                self.image(ref.target, base, ref.alt, where, file)

    def image(self, target: str, base: str, alt: str, where: str, file: str) -> None:
        """Check one local image reference and read the file once."""
        if not alt.strip() and file != COURSE_FILE:
            self.problem(where, "the image has no alt text", file)
        bad = images.path_problems(target)
        for message in bad:
            self.problem(where, message, file)
        resolved = markdown.resolve(base, target)
        if resolved is None:
            self.problem(where, f"image path {target!r} leaves the course folder", file)
            return
        if bad or resolved in self._images:
            return
        path = self.inside(resolved, where, file)
        if path is None:
            return
        if not path.is_file():
            self.problem(where, f"the image {resolved!r} does not exist", file)
            return
        try:
            data = path.read_bytes()
        except OSError as e:
            self.problem(where, f"the image {resolved!r} cannot be read: {e.strerror or e}", file)
            return
        for message in images.file_problems(posixpath.basename(resolved), data):
            self.problem(where, message, file)
        self._images[resolved] = Image(resolved, data, alt)

    def all_images(self) -> tuple[Image, ...]:
        return tuple(self._images[k] for k in sorted(self._images))


def _join(where: str, field: str) -> str:
    return f"{where}.{field}" if where else field


def _ref(node: object, index: int) -> str:
    key = node.get("key") if isinstance(node, Mapping) else None
    return key if isinstance(key, str) and key else str(index)


def _option(r: _Reader, node: object, where: str) -> Option:
    node = r.mapping(node, where)
    correct = node.get("correct", False)
    if not isinstance(correct, bool):
        r.problem(_join(where, "correct"), f"must be true or false, found {correct!r}")
    return Option(r.text(node, "text", where), correct is True)


def _question(r: _Reader, node: object, where: str) -> Question:
    node = r.mapping(node, where)
    if "explanation" in node:
        r.problem(
            _join(where, "explanation"),
            "explanation is not supported yet (spec 0011 AC-11 is still open), remove it",
        )
    options = tuple(
        _option(r, o, f"{where}.options[{i}]")
        for i, o in enumerate(r.items(node.get("options"), _join(where, "options")), 1)
    )
    return Question(
        key=r.text(node, "key", where),
        text=r.text(node, "text", where),
        marks=r.number(node, "marks", 1, where),
        options=options,
    )


def _quiz(r: _Reader, path: Path, lesson_of: Mapping[str, str]) -> Quiz | None:
    r.file = f"quizzes/{path.name}"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        r.problem("-", f"cannot read the file: {getattr(e, 'strerror', None) or e}")
        return None
    except yaml.YAMLError as e:
        r.problem("-", f"is not valid YAML: {e}")
        return None
    node = r.mapping(raw, "-")
    key = r.text(node, "key", "")
    questions = tuple(
        _question(r, q, f"questions[{_ref(q, i)}]")
        for i, q in enumerate(r.items(node.get("questions"), "questions"), 1)
    )
    return Quiz(
        key=key,
        title=r.text(node, "title", ""),
        lesson_key=lesson_of.get(key, ""),
        questions=questions,
        passing_percentage=r.number(node, "passing_percentage", DEFAULT_PASSING_PERCENTAGE, ""),
        max_attempts=r.number(node, "max_attempts", DEFAULT_MAX_ATTEMPTS, ""),
        file=r.file,
    )


def _block(r: _Reader, node: object, where: str) -> Block | None:
    if not isinstance(node, Mapping):
        r.problem(where, "a block must be a mapping with one of text, video or quiz")
        return None
    unknown = [k for k in node if k not in _BLOCK_KEYS]
    for k in unknown:
        r.problem(where, f"unknown block key {k!r}, use text, video or quiz")
    known = [k for k in _BLOCK_KEYS if k in node]
    if len(known) != 1:
        if not unknown or known:
            r.problem(
                where, f"a block needs exactly one of text, video or quiz, found {len(known)}"
            )
        return None
    kind = known[0]
    value = node[kind]
    if not isinstance(value, str):
        r.problem(where, f"{kind} must be text, found {type(value).__name__} {value!r}")
        return None
    if kind == "video":
        return VideoBlock(value)
    if kind == "quiz":
        return QuizBlock(value)
    md = r.guide(value, where)
    return TextBlock(posixpath.normpath(value), md or "")


def _lesson(r: _Reader, node: object, where: str) -> Lesson:
    node = r.mapping(node, where)
    blocks_raw = r.items(node.get("blocks"), _join(where, "blocks"))
    blocks = [_block(r, b, f"{where}.blocks[{i}]") for i, b in enumerate(blocks_raw)]
    return Lesson(
        key=r.text(node, "key", where),
        title=r.text(node, "title", where),
        blocks=tuple(b for b in blocks if b is not None),
    )


def _chapter(r: _Reader, node: object, where: str) -> Chapter:
    node = r.mapping(node, where)
    lessons = tuple(
        _lesson(r, x, f"{where}.lessons[{_ref(x, i)}]")
        for i, x in enumerate(r.items(node.get("lessons"), _join(where, "lessons")), 1)
    )
    return Chapter(r.text(node, "key", where), r.text(node, "title", where), lessons)


def _read_yaml(r: _Reader) -> Mapping[str, Any] | None:
    path = r.folder / COURSE_FILE
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        r.problem("-", f"cannot read the file: {getattr(e, 'strerror', None) or e}")
        return None
    except yaml.YAMLError as e:
        r.problem("-", f"is not valid YAML: {e}")
        return None
    if not isinstance(raw, Mapping):
        r.problem("-", "must be a mapping")
        return None
    return raw


def read_course(folder: Path) -> tuple[Course | None, tuple[Problem, ...]]:
    """Read one course folder. The course is None only when `course.yaml` cannot be parsed."""
    r = _Reader(folder)
    node = _read_yaml(r)
    if node is None:
        return None, tuple(r.problems)
    if node.get("format") != FORMAT or isinstance(node.get("format"), bool):
        r.problem(
            "format",
            f"{COURSE_FILE} must start with `format: {FORMAT}`, found {node.get('format')!r}",
        )
    chapters = tuple(
        _chapter(r, c, f"chapters[{_ref(c, i)}]")
        for i, c in enumerate(r.items(node.get("chapters"), "chapters"), 1)
    )
    lesson_of = {
        b.quiz_key: x.key
        for c in chapters
        for x in c.lessons
        for b in x.blocks
        if isinstance(b, QuizBlock)
    }
    quizzes: list[Quiz] = []
    quiz_dir = folder / "quizzes"
    for path in sorted(quiz_dir.glob("*.yaml")) if quiz_dir.is_dir() else ():
        if quiz := _quiz(r, path, lesson_of):
            quizzes.append(quiz)
    r.file = COURSE_FILE
    cover = r.text(node, "image", "", required=False)
    if cover:
        r.image(cover, "", "", "image", COURSE_FILE)
    key = r.text(node, "key", "")
    course = Course(
        key=key,
        title=r.text(node, "title", ""),
        chapters=chapters,
        quizzes=tuple(quizzes),
        short_introduction=r.text(node, "short_introduction", ""),
        description=r.text(node, "description", ""),
        image=posixpath.normpath(cover) if cover else "",
        images=r.all_images(),
    )
    if key != folder.name or not _KEY_RULE.fullmatch(folder.name):
        r.problem(
            "key",
            f"the folder name {folder.name!r} must equal the course key {key!r} "
            "and use only a-z, 0-9 and dashes, starting with a letter or digit",
            COURSE_FILE,
        )
    problems = [*r.problems, *check_course(course, folder.name)]
    guides = folder / "guides"
    for path in sorted(guides.rglob("*.md")) if guides.is_dir() else ():
        rel = path.relative_to(folder).as_posix()
        if rel not in r.used_guides:
            problems.append(Problem(folder.name, rel, "-", "no text block uses this guide", True))
    return course, tuple(problems)


def load_course(folder: Path) -> Course:
    """Read one course folder and return the checked course, or raise ContentError."""
    course, problems = read_course(folder)
    errors = tuple(p for p in problems if not p.warning)
    if course is None or errors:
        raise ContentError(errors)
    return course


def load_catalog(content_dir: Path) -> Catalog:
    """Read every course folder under `content/` and run the checks across courses."""
    problems: list[Problem] = []
    courses: dict[str, Course | None] = {}
    entries = sorted(content_dir.iterdir()) if content_dir.is_dir() else []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        rel = f"content/{entry.name}"
        if entry.is_file() and entry.name == COURSE_FILE:
            problems.append(Problem("", rel, "-", "move this file into content/<key>/"))
        elif entry.is_dir() and entry.name == "labs":
            problems.append(
                Problem("", rel + "/", "-", "move these guides into content/<key>/guides/")
            )
        elif entry.is_dir() and (entry / COURSE_FILE).is_file():
            course, found = read_course(entry)
            courses[entry.name] = course
            problems += found
        elif entry.is_dir():
            problems.append(
                Problem(
                    entry.name,
                    COURSE_FILE,
                    "-",
                    "this folder has no course.yaml: add one (see `content new`) or remove it",
                )
            )
            courses[entry.name] = None
    parsed = {k: c for k, c in courses.items() if c is not None}
    problems += check_across(parsed)
    return Catalog(courses, tuple(sorted(problems, key=Problem.sort_key)))
