"""Write a throwaway course folder (the 0011 layout) for the live integration tests."""

from pathlib import Path


def write_course(
    parent: Path,
    prefix: str,
    *,
    title: str,
    quiz_titles: tuple[str, str],
    q1_questions: str,
    q2_questions: str,
    short: str = "Throwaway course for an integration test.",
    description: str = "Made by the integration test & removed again.",
    lab_text: str = "# Lab\n\nDo the thing & report back.\n",
) -> Path:
    """Create `<parent>/<prefix>-course/` with two chapters, four lessons and two quiz files."""
    p = prefix
    folder = parent / f"{p}-course"
    (folder / "guides").mkdir(parents=True)
    (folder / "quizzes").mkdir()
    (folder / "guides" / "lab.md").write_text(lab_text)
    (folder / "quizzes" / "q1.yaml").write_text(
        f"key: {p}-q1\ntitle: {quiz_titles[0]}\nquestions:\n{q1_questions}\n"
    )
    (folder / "quizzes" / "q2.yaml").write_text(
        f"key: {p}-q2\ntitle: {quiz_titles[1]}\nquestions:\n{q2_questions}\n"
    )
    (folder / "course.yaml").write_text(
        f"""format: 1
key: {p}-course
title: {title}
short_introduction: {short}
description: {description}
chapters:
  - key: {p}-ch1
    title: Concepts
    lessons:
      - {{key: {p}-video, title: Video, blocks: [{{video: dQw4w9WgXcQ}}]}}
      - {{key: {p}-vq, title: Video quiz, blocks: [{{quiz: {p}-q1}}]}}
  - key: {p}-ch2
    title: Lab
    lessons:
      - {{key: {p}-lab, title: Lab guide, blocks: [{{text: guides/lab.md}}]}}
      - {{key: {p}-lq, title: Lab quiz, blocks: [{{quiz: {p}-q2}}]}}
"""
    )
    return folder


def question(key: str, text: str, *options: str) -> str:
    """Return one question as yaml for a quiz file; the first option is the correct one."""
    rows = ", ".join(
        f'{{text: "{o}"{", correct: true" if i == 0 else ""}}}' for i, o in enumerate(options)
    )
    return f'  - key: {key}\n    text: "{text}"\n    options: [{rows}]'
