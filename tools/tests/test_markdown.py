"""Unit tests for markdown and images: local image rules (AC-4)."""

import hashlib

import pytest

from nile_tools import images, markdown


def kinds(text: str) -> list[tuple[str, str]]:
    return [(r.kind, r.target) for r in markdown.scan(text)]


def test_local_and_remote_targets() -> None:
    for t in ("http://x/a.png", "HTTPS://x", "data:image/png;base64,x", "/files/a.png", "#top"):
        assert not markdown.is_local(t)
    for t in ("a.png", "../images/a.png", "images/a.png"):
        assert markdown.is_local(t)


def test_images_in_code_are_left_alone() -> None:
    text = "```\n![a](x.png)\n```\n`![b](y.png)` and ![c](z.png)\n~~~md\n![d](w.png)\n~~~\n"
    assert kinds(text) == [("image", "z.png")]


def test_an_unclosed_fence_runs_to_the_end() -> None:
    assert kinds("![a](a.png)\n```\n![b](b.png)\n") == [("image", "a.png")]


def test_title_and_angle_brackets_are_kept_when_rewriting() -> None:
    text = "![a](<my.png> \"t\") ![b](b.png 'x') ![c](https://x/c.png)"
    out = markdown.rewrite_images(text, "", {"my.png": "/files/1", "b.png": "/files/2"})
    assert out == "![a](</files/1> \"t\") ![b](/files/2 'x') ![c](https://x/c.png)"


def test_two_guides_reach_one_image() -> None:
    assert markdown.local_image_paths("![a](../images/x.png)", "guides") == ["images/x.png"]
    assert markdown.local_image_paths("![a](images/x.png)", "") == ["images/x.png"]


def test_a_path_that_leaves_the_folder_is_not_resolved() -> None:
    assert markdown.resolve("guides", "../../x.png") is None
    assert markdown.local_image_paths("![a](../../x.png)", "guides") == []


def test_refs_links_and_tags_are_found() -> None:
    text = '![a][r]\n[x](other.md)\n<img src="p.png">\n[ok](https://x)\n[top](#a)'
    assert kinds(text) == [
        ("ref-image", "![a][r]"),
        ("link", "other.md"),
        ("img-tag", "p.png"),
        ("link", "https://x"),
        ("link", "#a"),
    ]


def test_macros_are_found_with_their_line() -> None:
    assert markdown.macro_lines("a\n{{ Quiz('x') }}\n`{{`") == [2, 3]


def test_lines_are_counted() -> None:
    refs = markdown.scan("one\n\n![a](a.png)")
    assert refs[0].line == 3


@pytest.mark.parametrize(
    ("name", "data", "expect"),
    [
        ("a.png", b"\x89PNG\r\n\x1a\n", ""),
        ("a.jpg", b"\xff\xd8\xff\xe0", ""),
        ("a.jpeg", b"\xff\xd8\xff", ""),
        ("a.gif", b"GIF89a", ""),
        ("a.webp", b"RIFF\0\0\0\0WEBP", ""),
        ("a.svg", b"<svg/>", "must be png"),
        ("a.png", b"MZ\x90", "not really a png"),
        ("A.png", b"\x89PNG\r\n\x1a\n", "may only use"),
        ("a b.png", b"\x89PNG\r\n\x1a\n", "may only use"),
        ("a.PNG", b"\x89PNG\r\n\x1a\n", "may only use"),
    ],
)
def test_image_files(name: str, data: bytes, expect: str) -> None:
    found = " ".join(images.file_problems(name, data))
    assert (expect in found) if expect else not found


def test_size_limit_is_5_million_bytes() -> None:
    png = b"\x89PNG\r\n\x1a\n"
    assert not images.file_problems("a.png", png + b"0" * (5_000_000 - 8))
    assert images.file_problems("a.png", png + b"0" * (5_000_000 - 7))


@pytest.mark.parametrize("path", ["a.png?x=1", "a.png#f", "a%20b.png"])
def test_path_with_query_fragment_or_percent(path: str) -> None:
    assert images.path_problems(path)


def test_stored_name_uses_the_hash() -> None:
    data = b"abc"
    assert (
        images.stored_name("c", data, "a.png") == f"c-{hashlib.sha256(data).hexdigest()[:12]}-a.png"
    )


@pytest.mark.parametrize("target", ["mailto:a@b.c", "tel:+1555", "ftp://x/a", "MAILTO:a@b.c"])
def test_any_url_scheme_is_not_a_local_target(target: str) -> None:
    assert not markdown.is_local(target)


def test_a_clickable_image_is_one_image_and_no_local_link() -> None:
    text = "[![shot](img.png)](https://example.com)"
    found = markdown.scan(text)
    assert [r.target for r in found if r.kind == "image"] == ["img.png"]
    assert [r.target for r in found if r.kind == "link" and markdown.is_local(r.target)] == []


def test_a_clickable_image_with_a_local_link_target_still_counts_that_link() -> None:
    assert ("link", "other.md") in kinds("[![shot](img.png)](other.md)")


def test_a_run_of_bangs_does_not_hang() -> None:
    assert kinds("[" + "!" * 5000 + "](x.md") == []
