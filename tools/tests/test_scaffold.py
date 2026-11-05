"""Unit tests for `content new` (AC-9): the output passes `content check` with no edit."""

from pathlib import Path

import pytest

from nile_tools.contentfile import load_catalog
from nile_tools.scaffold import ScaffoldError, new_course


def test_the_new_course_passes_the_check_with_the_fixed_keys(tmp_path: Path) -> None:
    folder = new_course(tmp_path, "demo")
    assert sorted(p.name for p in folder.rglob("*") if p.is_file()) == [
        "course.yaml",
        "demo-quiz.yaml",
        "welcome.md",
    ]
    catalog = load_catalog(tmp_path)
    assert not catalog.problems
    course = catalog.ready()["demo"]
    assert course.title == "Demo"
    assert (course.chapters[0].key, course.chapters[0].lessons[0].key) == ("demo-ch-1", "demo-l-1")
    assert (course.quizzes[0].key, course.quizzes[0].questions[0].key) == ("demo-q-1", "demo-q-1-1")


def test_a_title_with_a_colon_is_still_valid_yaml(tmp_path: Path) -> None:
    new_course(tmp_path, "demo", 'Intro: "Nile"')
    assert load_catalog(tmp_path).ready()["demo"].title == 'Intro: "Nile"'


@pytest.mark.parametrize("key", ["Demo", "-demo", "de mo", "de_mo", ""])
def test_a_bad_key_is_refused_and_nothing_is_written(tmp_path: Path, key: str) -> None:
    with pytest.raises(ScaffoldError, match="course key"):
        new_course(tmp_path, key)
    assert list(tmp_path.iterdir()) == []


def test_an_existing_folder_is_refused_and_untouched(tmp_path: Path) -> None:
    new_course(tmp_path, "demo")
    (tmp_path / "demo" / "guides" / "welcome.md").write_text("mine")
    with pytest.raises(ScaffoldError, match="already exists"):
        new_course(tmp_path, "demo")
    assert (tmp_path / "demo" / "guides" / "welcome.md").read_text() == "mine"


def test_a_title_used_by_another_course_is_refused_ignoring_case(tmp_path: Path) -> None:
    new_course(tmp_path, "demo")
    with pytest.raises(ScaffoldError, match="already used by course 'demo'"):
        new_course(tmp_path, "other", "DEMO")
    assert not (tmp_path / "other").exists()
