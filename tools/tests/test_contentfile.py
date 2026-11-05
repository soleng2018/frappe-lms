"""Unit tests for nile_tools.contentfile: the folder loader and the catalog (AC-1 to AC-5)."""

from pathlib import Path

import pytest

from nile_tools.content import QuizBlock, TextBlock, VideoBlock
from nile_tools.contentfile import ContentError, load_catalog, load_course, read_course

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20

GOOD = """\
format: 1
key: c
title: Course
short_introduction: short
description: long
chapters:
  - key: ch
    title: Chapter
    lessons:
      - key: l1
        title: Mixed
        blocks:
          - video: dQw4w9WgXcQ
          - text: guides/a.md
          - quiz: q
"""
QUIZ = """\
key: q
title: Quiz
questions:
  - key: q1
    text: Which?
    options: [{text: A, correct: true}, {text: B}]
"""


def course_dir(root: Path, name: str = "c", yaml_text: str = GOOD, guide: str = "# A\n") -> Path:
    folder = root / name
    (folder / "guides").mkdir(parents=True, exist_ok=True)
    (folder / "quizzes").mkdir(exist_ok=True)
    (folder / "course.yaml").write_text(yaml_text)
    (folder / "guides" / "a.md").write_text(guide)
    (folder / "quizzes" / "q.yaml").write_text(QUIZ)
    return folder


def lines(folder: Path) -> str:
    _, problems = read_course(folder)
    return "\n".join(p.line() for p in problems)


def test_a_good_folder_loads_with_blocks_and_the_quiz_file(tmp_path: Path) -> None:
    course = load_course(course_dir(tmp_path))
    lesson = course.chapters[0].lessons[0]
    assert lesson.blocks == (
        VideoBlock("dQw4w9WgXcQ"),
        TextBlock("guides/a.md", "# A\n"),
        QuizBlock("q"),
    )
    quiz = course.quizzes[0]
    assert (quiz.lesson_key, quiz.passing_percentage, quiz.max_attempts, quiz.file) == (
        "l1",
        80,
        3,
        "quizzes/q.yaml",
    )


def test_the_course_in_the_repo_is_sound() -> None:
    catalog = load_catalog(Path(__file__).resolve().parents[2] / "content")
    assert not catalog.problems
    assert "nile-workshop" in catalog.ready()


def test_format_must_be_1(tmp_path: Path) -> None:
    bad = GOOD.replace("format: 1\n", "format: 2\n")
    assert "ERROR c/course.yaml: format:" in lines(course_dir(tmp_path, yaml_text=bad))
    assert "format:" in lines(course_dir(tmp_path, yaml_text=GOOD.replace("format: 1\n", "")))


def test_folder_name_must_equal_the_key_and_the_rule(tmp_path: Path) -> None:
    assert "must equal the course key" in lines(course_dir(tmp_path, "other"))
    folder = course_dir(tmp_path, "Bad_Name", GOOD.replace("key: c", "key: Bad_Name"))
    assert "a-z, 0-9 and dashes" in lines(folder)


def test_unparseable_yaml_skips_the_course(tmp_path: Path) -> None:
    course, problems = read_course(course_dir(tmp_path, yaml_text="key: [\n"))
    assert course is None
    assert problems[0].line().startswith("ERROR c/course.yaml: -: is not valid YAML")


def test_block_shapes(tmp_path: Path) -> None:
    text = GOOD.replace(
        "          - quiz: q\n",
        "          - quiz: q\n          - {text: guides/a.md, video: dQw4w9WgXcQ}\n"
        "          - {image: x.png}\n          - video: 12345678901\n          - plain\n",
    )
    found = lines(course_dir(tmp_path, yaml_text=text))
    assert "blocks[3]: a block needs exactly one of text, video or quiz, found 2" in found
    assert "blocks[4]: unknown block key 'image', use text, video or quiz" in found
    assert "blocks[5]: video must be text, found int 12345678901" in found
    assert "blocks[6]: a block must be a mapping" in found


def test_a_missing_or_escaping_guide(tmp_path: Path) -> None:
    text = GOOD.replace("guides/a.md", "guides/none.md")
    assert "the file 'guides/none.md' does not exist" in lines(course_dir(tmp_path, yaml_text=text))
    text = GOOD.replace("guides/a.md", "../x.md")
    assert "points outside the course folder" in lines(course_dir(tmp_path / "t", yaml_text=text))


def test_a_macro_in_a_guide_is_named_with_its_line(tmp_path: Path) -> None:
    found = lines(course_dir(tmp_path, guide="one\n{{ Quiz('x') }}\n"))
    assert "ERROR c/guides/a.md: line 2: {{ starts a macro" in found


def test_images_are_checked_and_read_once(tmp_path: Path) -> None:
    folder = course_dir(tmp_path, guide="![ok](../images/a.png)\n![](../images/a.png)\n")
    (folder / "images").mkdir()
    (folder / "images" / "a.png").write_bytes(PNG)
    course, problems = read_course(folder)
    assert [p.message for p in problems] == ["the image has no alt text"]
    assert course is not None
    assert [i.path for i in course.images] == ["images/a.png"]


def test_image_problems_all_at_once(tmp_path: Path) -> None:
    guide = (
        "![a](../images/missing.png)\n![a](../images/x.svg)\n![a](../images/fake.png)\n"
        '![a](<../images/Big Name.png>)\n![a][r]\n[go](other.md)\n<img src="p.png">\n'
        "![a](../../out.png)\n![a](a.png?x)\n```\n![a](skip.png)\n```\n"
    )
    folder = course_dir(tmp_path, guide=guide)
    (folder / "images").mkdir()
    (folder / "images" / "x.svg").write_text("<svg/>")
    (folder / "images" / "fake.png").write_bytes(b"MZ")
    (folder / "images" / "Big Name.png").write_bytes(PNG)
    found = lines(folder)
    for part in (
        "line 1: the image 'images/missing.png' does not exist",
        "line 2: image 'x.svg' must be",
        "line 3: image 'fake.png' is not really a png",
        "line 4: image file name 'Big Name.png'",
        "line 5: reference style images",
        "line 6: a local link to 'other.md'",
        "line 7: a local <img>",
        "line 8: image path '../../out.png' leaves the course folder",
        "line 9: image path 'a.png?x' must not contain '?'",
    ):
        assert part in found
    assert "skip.png" not in found


def test_a_symlink_that_leaves_the_folder_is_refused(tmp_path: Path) -> None:
    folder = course_dir(tmp_path, guide="![a](../images/a.png)\n")
    (folder / "images").mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG)
    (folder / "images" / "a.png").symlink_to(outside)
    assert "points outside the course folder" in lines(folder)


def test_the_cover_image(tmp_path: Path) -> None:
    folder = course_dir(
        tmp_path, yaml_text=GOOD.replace("chapters:", "image: images/cover.png\nchapters:")
    )
    (folder / "images").mkdir()
    (folder / "images" / "cover.png").write_bytes(PNG)
    course, problems = read_course(folder)
    assert not problems and course is not None
    assert course.image == "images/cover.png"
    assert [i.path for i in course.images] == ["images/cover.png"]


def test_an_unused_guide_is_only_a_warning(tmp_path: Path) -> None:
    folder = course_dir(tmp_path)
    (folder / "guides" / "draft.md").write_text("draft")
    _, problems = read_course(folder)
    assert [p.line() for p in problems] == [
        "WARN c/guides/draft.md: -: no text block uses this guide"
    ]
    load_course(folder)  # a warning does not stop a load


def test_load_course_raises_with_every_problem(tmp_path: Path) -> None:
    with pytest.raises(ContentError) as e:
        load_course(course_dir(tmp_path, yaml_text=GOOD.replace("title: Course\n", "")))
    assert "title: must be text" in str(e.value)


def _with_option_explanation(folder: Path, value: str) -> None:
    option = "{text: A, correct: true, explanation: " + value + "}"
    (folder / "quizzes" / "q.yaml").write_text(QUIZ.replace("{text: A, correct: true}", option))


def test_an_option_explanation_is_read_and_trimmed(tmp_path: Path) -> None:
    folder = course_dir(tmp_path)
    _with_option_explanation(folder, '"  Because  "')
    course = load_course(folder)
    options = course.quizzes[0].questions[0].options
    assert [o.explanation for o in options] == ["Because", ""]


def test_a_question_level_explanation_names_the_option_field(tmp_path: Path) -> None:
    folder = course_dir(tmp_path)
    (folder / "quizzes" / "q.yaml").write_text(
        QUIZ.replace("    text: Which?", "    text: Which?\n    explanation: Because")
    )
    assert "belongs on an option" in lines(folder)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("12", "must be text"),
        ('""', "is empty"),
        ('"   "', "is empty"),
        ("null", "is empty"),
        ('"' + "x" * 1001 + '"', "1001 characters"),
    ],
)
def test_a_bad_option_explanation_is_refused(tmp_path: Path, value: str, message: str) -> None:
    folder = course_dir(tmp_path)
    _with_option_explanation(folder, value)
    assert message in lines(folder)


def test_an_explanation_of_1000_characters_is_allowed(tmp_path: Path) -> None:
    folder = course_dir(tmp_path)
    _with_option_explanation(folder, '"' + "x" * 1000 + '"')
    assert lines(folder) == ""


def test_the_explanation_limit_counts_after_trimming(tmp_path: Path) -> None:
    # covers: AC-11. 1000 characters plus padding is allowed; 1001 once trimmed is not.
    folder = course_dir(tmp_path)
    _with_option_explanation(folder, '"  ' + "x" * 1000 + '  "')
    assert lines(folder) == ""


def test_an_explanation_keeps_markdown_and_html_as_typed(tmp_path: Path) -> None:
    # covers: AC-11. It is plain text, so nothing is stripped or rewritten.
    folder = course_dir(tmp_path)
    _with_option_explanation(folder, '"**Bold** <b>x</b>"')
    option = load_course(folder).quizzes[0].questions[0].options[0]
    assert option.explanation == "**Bold** <b>x</b>"


def test_an_unused_quiz_file(tmp_path: Path) -> None:
    folder = course_dir(tmp_path)
    (folder / "quizzes" / "extra.yaml").write_text(
        QUIZ.replace("key: q\n", "key: extra\n").replace("q1", "e1")
    )
    assert "quizzes/extra.yaml: key: quiz 'extra' is not used by any quiz block" in lines(folder)


# ---- the catalog


def test_the_catalog_finds_every_folder_and_ignores_dot_names(tmp_path: Path) -> None:
    course_dir(tmp_path, "c")
    (tmp_path / ".hidden").mkdir()
    catalog = load_catalog(tmp_path)
    assert list(catalog.courses) == ["c"] and not catalog.problems


def test_legacy_files_and_a_folder_without_yaml(tmp_path: Path) -> None:
    (tmp_path / "course.yaml").write_text("x")
    (tmp_path / "labs").mkdir()
    (tmp_path / "stray").mkdir()
    found = [p.line() for p in load_catalog(tmp_path).problems]
    assert "ERROR content/course.yaml: -: move this file into content/<key>/" in found
    assert "ERROR content/labs/: -: move these guides into content/<key>/guides/" in found
    assert any(
        x.startswith("ERROR stray/course.yaml: -: this folder has no course.yaml") for x in found
    )


def test_cross_course_clashes_block_both_but_not_a_third(tmp_path: Path) -> None:
    course_dir(tmp_path, "c")
    course_dir(tmp_path, "d", GOOD.replace("key: c", "key: d"))
    third = (
        GOOD.replace("key: c\n", "key: e\n")
        .replace("title: Course", "title: Other")
        .replace("key: l1", "key: l9")
        .replace("key: ch\n", "key: ch9\n")
    )
    folder = course_dir(tmp_path, "e", third)
    (folder / "quizzes" / "q.yaml").write_text(
        QUIZ.replace("key: q\n", "key: q9\n").replace("q1", "q91")
    )
    folder.joinpath("course.yaml").write_text(third.replace("quiz: q", "quiz: q9"))
    catalog = load_catalog(tmp_path)
    assert sorted(catalog.blocked()) == ["c", "d"]
    assert list(catalog.ready()) == ["e"]
    found = [p.line() for p in catalog.problems]
    assert "ERROR c/course.yaml: title: the title is also used by d (case ignored)" in found


def test_problems_are_sorted_by_course_file_where(tmp_path: Path) -> None:
    course_dir(tmp_path, "b", GOOD.replace("key: c", "key: b").replace("title: Course", "title: B"))
    course_dir(tmp_path, "a", GOOD.replace("key: c", "key: x"))
    keys = [(p.course, p.file, p.where) for p in load_catalog(tmp_path).problems]
    assert keys == sorted(keys)
