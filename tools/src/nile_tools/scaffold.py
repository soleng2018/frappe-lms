"""`content new`: write a small course folder that already passes `content check`."""

import json
import re
from pathlib import Path

from nile_tools.contentfile import load_catalog

__all__ = ["ScaffoldError", "new_course"]

_KEY_RULE = re.compile(r"[a-z0-9][a-z0-9-]*")


class ScaffoldError(Exception):
    """The course cannot be created; the message says why and nothing was written."""


def default_title(key: str) -> str:
    """Return the key with dashes as spaces and the first letter in upper case."""
    text = key.replace("-", " ")
    return text[:1].upper() + text[1:]


def _course_yaml(key: str, title: str) -> str:
    return f"""format: 1
key: {key}
title: {json.dumps(title)}
short_introduction: A short line that shows on the course card.
description: Say what a learner will do and learn in this course.
chapters:
  - key: {key}-ch-1
    title: Getting started
    lessons:
      - key: {key}-l-1
        title: Welcome
        blocks:
          - text: guides/welcome.md
          - quiz: {key}-q-1
"""


def _quiz_yaml(key: str) -> str:
    return f"""key: {key}-q-1
title: Welcome quiz
passing_percentage: 80
max_attempts: 3
questions:
  - key: {key}-q-1-1
    text: Did you read the welcome guide?
    options:
      - {{text: "Yes", correct: true}}
      - {{text: "No"}}
"""


_GUIDE = """# Welcome

Write the guide here in markdown. Add an image with `![a short description](../images/name.png)`.
"""


def new_course(content_dir: Path, key: str, title: str | None = None) -> Path:
    """Create `content/<key>/` and return its path, or raise ScaffoldError and write nothing."""
    if not _KEY_RULE.fullmatch(key):
        raise ScaffoldError(
            f"course key {key!r} must use only a-z, 0-9 and dashes, starting with a letter or digit"
        )
    folder = content_dir / key
    if folder.exists():
        raise ScaffoldError(f"{folder} already exists, nothing was written")
    title = title if title is not None else default_title(key)
    for other_key, other in load_catalog(content_dir).courses.items():
        if other is not None and other.title.strip().casefold() == title.strip().casefold():
            raise ScaffoldError(f"the title {title!r} is already used by course {other_key!r}")
    (folder / "guides").mkdir(parents=True)
    (folder / "quizzes").mkdir()
    (folder / "course.yaml").write_text(_course_yaml(key, title), encoding="utf-8")
    (folder / "guides" / "welcome.md").write_text(_GUIDE, encoding="utf-8")
    (folder / "quizzes" / f"{key}-quiz.yaml").write_text(_quiz_yaml(key), encoding="utf-8")
    return folder
