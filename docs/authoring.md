# Authoring a course

A course is one folder in git. You add a course by committing a folder under `content/`. You do not change any code and you do not click in the LMS Desk. This page lists every file, every field, every rule and every message the check can print, with the fix for each.

Run the check on your own machine before you commit. It reads only the repository, needs no `.env` and makes no network call.

## The three commands

Run each one with `make tools CMD="..."`.

| Command | What it does | Needs |
|---|---|---|
| `content new <course-key> [--title TEXT]` | Creates `content/<course-key>/` with one chapter, one lesson, one guide and one quiz. The result passes `content check` with no edit. | Nothing |
| `content check [course-key]` | Prints every problem in every course (or one) at once. | Nothing |
| `sync [course-key] [--check]` | Makes the LMS match git for every course (or one). `--check` only lists what would change. | The stack and the service user key in `.env` |

Exit codes: `0` everything is fine. `1` any problem, any blocked course, any difference in `--check`, a refused `content new`, a missing `.env`, or an LMS failure. `2` you used the command line wrongly.

`content check` prints `ok <course>` for each sound course and `ERROR <course>/<file>: <where>: <message>` for each problem, sorted by course, file and where. A `WARN` line is only a hint and never changes the exit code. A commit that touches `content/` runs the same check and stops on any problem (run `make hooks` once per clone).

### A worked example

`content new demo` writes this. It is the smallest course that passes the check.

```
content/demo/
  course.yaml
  guides/welcome.md
  quizzes/demo-quiz.yaml
```

```yaml
# content/demo/course.yaml
format: 1
key: demo
title: "Demo"
short_introduction: A short line that shows on the course card.
description: Say what a learner will do and learn in this course.
chapters:
  - key: demo-ch-1
    title: Getting started
    lessons:
      - key: demo-l-1
        title: Welcome
        blocks:
          - text: guides/welcome.md
          - quiz: demo-q-1
```

```yaml
# content/demo/quizzes/demo-quiz.yaml
key: demo-q-1
title: Welcome quiz
passing_percentage: 80
max_attempts: 3
questions:
  - key: demo-q-1-1
    text: Did you read the welcome guide?
    options:
      - {text: "Yes", correct: true}
      - {text: "No"}
```

## The folder

```
content/<course-key>/
  course.yaml        the course, its chapters and lessons
  guides/*.md        markdown for text blocks
  quizzes/*.yaml     one quiz per file
  images/*           png, jpg, jpeg, gif, webp
```

The folder name must equal the course `key` and match `[a-z0-9][a-z0-9-]*`. Names that start with a dot are ignored. A folder under `content/` without a `course.yaml` is a problem.

## course.yaml

| Field | Type | Required | Notes |
|---|---|---|---|
| `format` | number | yes | Must be `1`. |
| `key` | text | yes | Equals the folder name. |
| `title` | text | yes | Must differ from every other course title (case ignored). |
| `short_introduction` | text | yes | Shows on the course card. |
| `description` | text | yes | |
| `image` | path | no | A cover image, relative to the course folder. |
| `chapters` | list | yes | In reading order. Each needs at least one lesson. |

Chapter: `key` (text), `title` (text), `lessons` (list). Lesson: `key` (text), `title` (text), `blocks` (a list with at least one block).

### Blocks

A block is a mapping with exactly one of these keys.

| Key | Value | Renders as |
|---|---|---|
| `text` | A path to a markdown file in the course folder | The file, as written |
| `video` | The 11 character YouTube id, written as text | `{{ YouTubeVideo("<id>") }}` |
| `quiz` | A quiz key | `{{ Quiz("<quiz name>") }}` |

A lesson may hold any number of `text` blocks, at most one `video` and at most one `quiz`. The lesson body in the LMS is each block, stripped, joined by one blank line, in the order you wrote them.

## Quiz files

Each file in `quizzes/` (any name ending in `.yaml`) is one quiz.

| Field | Type | Required | Notes |
|---|---|---|---|
| `key` | text | yes | |
| `title` | text | yes | |
| `passing_percentage` | number | no | 80 to 100. Default 80. |
| `max_attempts` | number | no | At least 1. Default 3. |
| `questions` | list | yes | At least one question. |

Question: `key` (text), `text` (text), `marks` (number, default 1), `options` (2 to 4 items). Option: `text` (text, not empty, not repeated) and `correct` (true or false). At least one option is correct. In YAML write `"yes"` and `"no"` in quotes, because bare `no` means false.

Every quiz must be used by exactly one quiz block in a lesson of the same course.

A question `explanation` is not supported yet. The check refuses it so you do not think it works. This waits on a design decision (spec 0011, AC-11).

## Keys

Every chapter, lesson, quiz and question has a `key`. The sync finds a record by its key, so you can rename a title freely. Changing a key makes a new record and detaches the old one. The LMS keeps one set of keys for the whole site, so a key must be unique across all courses. Start every key with the course key, as `content new` does.

## Images

Write `![alt text](path)` in a guide. The path is relative to the guide, so `../images/a.png` from `guides/x.md`. Fenced code and inline code are left alone.

The check refuses an image that: does not exist, has empty alt text, is not png, jpg, jpeg, gif or webp (SVG is refused because it can carry script), has first bytes that do not match its type, is over 5 MB (1 MB is 1,000,000 bytes), has a file name outside `a-z 0-9 . _ -`, has `?`, `#` or `%` in its path, or leaves the course folder (a symlink that leaves it too). It also refuses a reference style image (`![a][r]`), a local `<img src>`, and a local link that is not an image (`[x](other.md)`, a pdf). Links that start with `http:`, `https:`, `data:`, `/` or `#` are not local.

`sync` uploads each image to the LMS as a public file named `<course-key>-<12 hex of the sha256>-<file name>` and writes that URL into the lesson body. A second run uploads nothing. A changed image is a new file with a new name, and the old file stays. Anyone who has an image URL can load it, so never put a secret in an image.

## What sync does with several courses

- Every course folder is checked first. A course with a problem is skipped whole, and nothing is written for it. The other courses still sync.
- A course is also blocked when its title equals another LMS course or `AUTHENTIK_ADMIN_GROUP`, or when one of its keys is held under another LMS course.
- Every line of output starts with `[<course-key>]`. At the end the blocked courses are listed with the reason, and the exit code is 1 if any course was blocked.
- A second run on unchanged content writes nothing, uploads nothing and prints `[<course-key>] nothing to change`.
- A course in the LMS whose folder is gone is listed as `has no folder in content/, left alone`. Nothing is changed or unpublished.
- Nothing is ever deleted. A removed lesson, chapter, quiz or question leaves the course and stays in the LMS.

## Messages and fixes

| Message (shortened) | Fix |
|---|---|
| `move this file into content/<key>/` | Move the old `content/course.yaml` into a course folder. |
| `move these guides into content/<key>/guides/` | Move the old `content/labs/` files into `guides/` and point text blocks at them. |
| `this folder has no course.yaml` | Add one (run `content new`) or delete the folder. |
| `is not valid YAML`, `must be a mapping` | Fix the YAML syntax of that file. |
| `must start with format: 1` | Add `format: 1` as the first line of `course.yaml`. |
| `the folder name ... must equal the course key` | Rename the folder or the `key` so they match, using only a-z, 0-9 and dashes. |
| `must be text, found ...` | Quote the value. A number or `no` is not text. |
| `a block needs exactly one of text, video or quiz` | Keep one key per block. |
| `unknown block key` | Use `text`, `video` or `quiz`. |
| `the file ... does not exist`, `points outside the course folder` | Fix the path. It must be a file inside the course folder. |
| `the file ... is empty` | Write the guide, or remove the block. |
| `{{ starts a macro in the LMS` | Remove `{{` from the guide. It would run as a macro. |
| `no text block uses this guide` (WARN) | Use it in a block, or leave it as a draft. |
| `a lesson needs at least one block`, `a chapter needs at least one lesson` | Add one. |
| `a lesson may hold at most one video block` or `quiz block` | Split it into two lessons. |
| `video ... must be the 11 character video id` | Write the id, not the link. |
| `quiz ... has no file in quizzes/` | Add the quiz file, or fix the key. |
| `quiz ... is not used by any quiz block` | Add a quiz block for it, or delete the file. |
| `quiz ... is used by N quiz blocks` | Keep one block per quiz. |
| `passing_percentage`, `max_attempts`, `no questions` | Use 80 to 100, at least 1, and at least one question. |
| `... options, must be 2 to 4`, `no correct option`, `an empty option`, `repeats the option` | Fix the options of that question. |
| `open ended, so it is never graded` | Use choices. |
| `explanation is not supported yet` | Remove the `explanation` line. |
| `... key ... is used more than once` | Make the key unique in the course. |
| `... key ... is also used by <course>` | Prefix the key with its course key. |
| `the title is also used by <course>` | Give the course a different title. |
| `the image ... does not exist`, `has no alt text` | Add the file, or write the alt text. |
| `image file name ... may only use`, `must be png, jpg ...`, `is not really a ...`, `the limit is` | Rename, convert or shrink the image. |
| `image path ... must not contain`, `leaves the course folder` | Use a plain relative path. |
| `reference style images are not supported`, `a local <img>`, `a local link to ...` | Use `![alt](path)`. Do not link to local files. |
