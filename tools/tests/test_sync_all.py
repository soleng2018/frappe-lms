"""Unit tests for sync_all: many courses, isolation, images, the blocked list (AC-4, AC-7)."""

from pathlib import Path

import httpx
from fake_lms import FakeLms

from nile_tools.contentfile import load_catalog
from nile_tools.sync import sync_all

PNG = b"\x89PNG\r\n\x1a\n" + b"1" * 20


def write_course(root: Path, key: str, *, guide: str = "# Hi\n", title: str | None = None) -> Path:
    folder = root / key
    (folder / "guides").mkdir(parents=True)
    (folder / "quizzes").mkdir()
    (folder / "course.yaml").write_text(
        f"""format: 1
key: {key}
title: {title or "Course " + key}
short_introduction: s
description: d
chapters:
  - key: {key}-ch
    title: Chapter
    lessons:
      - key: {key}-l
        title: Mixed
        blocks:
          - video: dQw4w9WgXcQ
          - text: guides/a.md
          - quiz: {key}-q
"""
    )
    (folder / "guides" / "a.md").write_text(guide)
    (folder / "quizzes" / "q.yaml").write_text(
        f"key: {key}-q\ntitle: Quiz {key}\nquestions:\n  - key: {key}-q1\n    text: Q?\n"
        "    options: [{text: A, correct: true}, {text: B}]\n"
    )
    return folder


def run(
    fake: FakeLms, root: Path, *, only: str | None = None, check: bool = False
) -> tuple[int, list[str], list[str]]:
    out: list[str] = []
    err: list[str] = []
    code = sync_all(
        fake.client(),
        load_catalog(root),
        only=only,
        check=check,
        say=out.append,
        err=err.append,
        admin_group="hol-admins",
    )
    return code, out, err


def test_every_course_syncs_with_its_prefix_and_the_body_has_every_block(tmp_path: Path) -> None:
    write_course(tmp_path, "a")
    write_course(tmp_path, "b")
    fake = FakeLms()
    code, out, _ = run(fake, tmp_path)
    assert code == 0
    assert all(line.startswith(("[a] ", "[b] ")) for line in out)
    body = fake.by_key("Course Lesson", "a-l")["body"]
    quiz = fake.by_key("LMS Quiz", "a-q")["name"]
    assert body == f'{{{{ YouTubeVideo("dQw4w9WgXcQ") }}}}\n\n# Hi\n\n{{{{ Quiz("{quiz}") }}}}'
    assert fake.by_key("Course Lesson", "a-l")["youtube"] == "dQw4w9WgXcQ"
    assert fake.by_key("Course Lesson", "a-l")["quiz_id"] == quiz


def test_a_second_run_writes_nothing_and_says_so_per_course(tmp_path: Path) -> None:
    write_course(tmp_path, "a")
    write_course(tmp_path, "b")
    fake = FakeLms()
    run(fake, tmp_path)
    before = len(fake.writes)
    code, out, _ = run(fake, tmp_path)
    assert code == 0 and len(fake.writes) == before
    assert out == ["[a] nothing to change", "[b] nothing to change"]
    assert run(fake, tmp_path, check=True)[1] == out


def test_reordering_blocks_updates_the_same_lesson(tmp_path: Path) -> None:
    write_course(tmp_path, "a")
    fake = FakeLms()
    run(fake, tmp_path)
    lesson = fake.by_key("Course Lesson", "a-l")["name"]
    yaml = tmp_path / "a" / "course.yaml"
    yaml.write_text(
        yaml.read_text().replace(
            "          - video: dQw4w9WgXcQ\n          - text: guides/a.md\n",
            "          - text: guides/a.md\n          - video: dQw4w9WgXcQ\n",
        )
    )
    assert run(fake, tmp_path)[0] == 0
    assert fake.by_key("Course Lesson", "a-l")["name"] == lesson
    assert fake.by_key("Course Lesson", "a-l")["body"].startswith("# Hi")
    assert len(fake.of("Course Lesson")) == 1


def test_a_bad_course_is_skipped_and_listed_while_the_others_sync(tmp_path: Path) -> None:
    write_course(tmp_path, "a", guide="{{ Quiz('x') }}")
    write_course(tmp_path, "b")
    fake = FakeLms()
    code, out, err = run(fake, tmp_path)
    assert code == 1
    assert [d["nile_key"] for d in fake.of("LMS Course").values()] == ["b"]
    assert any(line.startswith("ERROR a/guides/a.md: line 1:") for line in err)
    assert any(line.startswith("[a] blocked: guides/a.md: line 1:") for line in out)


def test_an_lms_failure_stops_only_that_course(tmp_path: Path) -> None:
    for key in "abc":
        write_course(tmp_path, key)
    fake = FakeLms()
    fake.fail_write = lambda n, m, d: (
        httpx.Response(500, json={"exc_type": "ValidationError"})
        if d == "Course Chapter" and not fake.of("Course Chapter")
        else None
    )
    code, out, _ = run(fake, tmp_path)
    assert code == 1
    assert any(line.startswith("[a] blocked: ") for line in out)
    assert {d["nile_key"] for d in fake.of("LMS Course").values()} >= {"b", "c"}


def test_a_title_clash_with_the_lms_or_the_admin_group_blocks_the_course(tmp_path: Path) -> None:
    write_course(tmp_path, "a", title="Taken")
    write_course(tmp_path, "b", title="hol-admins")
    write_course(tmp_path, "c")
    fake = FakeLms()
    fake.seed("LMS Course", "X-1", title="Taken", nile_key="other")
    code, out, _ = run(fake, tmp_path)
    assert code == 1
    assert any(line.startswith("[a] blocked: refusing to sync: another LMS Course") for line in out)
    assert any(line.startswith("[b] blocked: refusing to sync: course title") for line in out)
    assert "c" in {d["nile_key"] for d in fake.of("LMS Course").values()}


def test_a_key_held_under_another_course_names_both(tmp_path: Path) -> None:
    write_course(tmp_path, "a")
    fake = FakeLms()
    fake.seed("LMS Course", "Other-1", title="Elsewhere", nile_key="elsewhere")
    fake.seed("Course Chapter", "Ch-1", nile_key="a-ch", title="x", course="Other-1")
    code, out, _ = run(fake, tmp_path)
    assert code == 1
    assert any(
        line.startswith(
            "[a] blocked: refusing to sync: Course Chapter a-ch is held by LMS course 'Elsewhere'"
        )
        for line in out
    )


def test_one_course_only_and_an_unknown_key(tmp_path: Path) -> None:
    write_course(tmp_path, "a")
    write_course(tmp_path, "b")
    fake = FakeLms()
    code, out, _ = run(fake, tmp_path, only="b")
    assert code == 0 and all(line.startswith("[b] ") for line in out)
    assert [d["nile_key"] for d in fake.of("LMS Course").values()] == ["b"]
    code, _, err = run(fake, tmp_path, only="zzz")
    assert code == 1 and err == ["ERROR unknown course 'zzz'; known courses: a, b"]


def test_a_course_key_hides_other_courses_blocked_lines(tmp_path: Path) -> None:
    # covers: AC-7. With a course key, only that course is shown and counted.
    write_course(tmp_path, "a")
    broken = write_course(tmp_path, "b")
    (broken / "course.yaml").write_text("format: 7\nkey: b\n")
    fake = FakeLms()
    code, out, _ = run(fake, tmp_path, only="a")
    assert code == 0 and all(line.startswith("[a] ") for line in out)
    code, out, _ = run(fake, tmp_path)
    assert code == 1 and any(line.startswith("[b] blocked") for line in out)


def test_a_course_with_no_folder_is_listed_and_left_alone(tmp_path: Path) -> None:
    write_course(tmp_path, "a")
    fake = FakeLms()
    fake.seed("LMS Course", "Old-1", title="Old", nile_key="old")
    code, out, _ = run(fake, tmp_path)
    assert code == 0
    assert "course Old-1 (old) has no folder in content/, left alone" in out
    assert fake.of("LMS Course")["Old-1"]["title"] == "Old"
    assert run(fake, tmp_path, check=True)[0] == 1
    assert "course Old-1 (old) has no folder" not in "".join(run(fake, tmp_path, only="a")[1])


def test_images_upload_once_and_the_body_holds_the_url(tmp_path: Path) -> None:
    folder = write_course(tmp_path, "a", guide="![shot](../images/s.png)\n")
    (folder / "images").mkdir()
    (folder / "images" / "s.png").write_bytes(PNG)
    fake = FakeLms()
    code, out, _ = run(fake, tmp_path)
    assert code == 0
    (file,) = fake.of("File").values()
    assert file["file_name"].startswith("a-") and file["file_name"].endswith("-s.png")
    assert file["is_private"] == 0
    assert f"![shot]({file['file_url']})" in fake.by_key("Course Lesson", "a-l")["body"]
    assert "1 images uploaded" in out[-1]
    before = len(fake.writes)
    assert run(fake, tmp_path)[1] == ["[a] nothing to change"]
    assert len(fake.writes) == before


def test_a_changed_image_is_a_new_file_and_updates_the_body(tmp_path: Path) -> None:
    folder = write_course(tmp_path, "a", guide="![shot](../images/s.png)\n")
    (folder / "images").mkdir()
    (folder / "images" / "s.png").write_bytes(PNG)
    fake = FakeLms()
    run(fake, tmp_path)
    (folder / "images" / "s.png").write_bytes(PNG + b"2")
    assert run(fake, tmp_path)[0] == 0
    assert len(fake.of("File")) == 2
    assert fake.of("File")  # nothing deleted
    urls = [f["file_url"] for f in fake.of("File").values()]
    assert urls[1] in fake.by_key("Course Lesson", "a-l")["body"]


def test_check_uploads_nothing_and_reports_the_missing_image(tmp_path: Path) -> None:
    folder = write_course(tmp_path, "a", guide="![shot](../images/s.png)\n")
    (folder / "images").mkdir()
    (folder / "images" / "s.png").write_bytes(PNG)
    fake = FakeLms()
    run(fake, tmp_path)
    (folder / "images" / "s.png").write_bytes(PNG + b"3")
    before = len(fake.writes)
    code, out, _ = run(fake, tmp_path, check=True)
    assert code == 1 and len(fake.writes) == before
    assert "[a] would upload image images/s.png" in out
