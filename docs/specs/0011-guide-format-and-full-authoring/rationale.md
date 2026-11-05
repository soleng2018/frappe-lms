# 0011 Rationale: guide format and full authoring

## Context

> ⚠️ Premise note: The design assumes that LMS renders a video macro, text and a quiz macro together in one lesson body, that a lesson can still be completed, and that a public image shows in a lesson page and on the course card. None of this has been proven on the live site. Build task 1 probes all three, and the build stops and comes back to `/architect` if one fails.

The workshop certifies students for a hands on lab. The brief asks for a format to create guides, stored in git and pushed to Frappe. Spec 0005 built the thin version: one `content/course.yaml`, one course, three fixed lesson types, quizzes inside the same file, and a markdown file per lab. It said feature 11 would replace the format.

Three needs push past the thin version. The workshop will have more than one course, and spec 0009 already relies on several courses (a learner is enrolled in the one named by their group). Authors want a lesson to be more than one thing: a video with its transcript, a lab with an introduction, a lesson with no quiz. And lab guides need screenshots and diagrams.

The content is also checked in git and reviewed by people who are not the LMS operator, so the format has to be readable, and a mistake must show up early, before a sync reaches learners. Today the check only runs inside `sync`, and it blocks everything when one thing is wrong.

The existing code is a loader (`contentfile.py`), a pure model and check (`content.py`), a pure planner (`plan.py`), and a sync loop (`sync.py`). The planner and the sync loop already read all LMS course titles, so many courses is mostly a loop and a stricter check, while the lesson shape is a real change to the model.

## Options considered

### Option 1: A folder per course, lessons built from ordered blocks, per course error isolation

Each course lives in `content/<course-key>/` with `course.yaml`, `guides/`, `quizzes/` and `images/`. A lesson is a list of `text`, `video` and `quiz` blocks. Checks run offline for every course and across courses. Sync loops over courses and isolates each one.

**Pros**:
- A course is one reviewable, movable unit, and two authors seldom touch the same files.
- Blocks give the mix of content the authors asked for, in a visible order.
- The offline check and the commit hook find mistakes before sync.
- Fits the existing planner: only the lesson fields and the loop change.

**Cons**:
- More files and a new shape to learn.
- Keys must be globally unique, so authors prefix them.
- Images need an upload step and a probe of private files.

### Option 2: Keep one file, turn it into a list of courses

`content/courses.yaml` holds every course. The three lesson types stay.

**Pros**:
- Smallest change to the loader.
- One file to read.

**Cons**:
- Every author edits the same file, so merge conflicts follow.
- Does not give the mixed lessons the authors asked for.
- The file grows without bound.

### Option 3: A folder per course, but a lesson has fixed optional fields

A lesson may set `text`, `video`, `lab` and `quiz`, always shown in that fixed order.

**Pros**:
- Simpler to read and to check.
- No block list to learn.

**Cons**:
- Cannot put a quiz before a video, or text after a lab.
- Needs a new field for every new kind of content.

### Option 4: One markdown file per lesson with a yaml header

Each lesson is a `.md` file with a header (`key`, `title`) and macros in the body. Chapters are folders.

**Pros**:
- Very natural for people who write markdown.
- Folder order is the lesson order.

**Cons**:
- Order and identity then depend on file and folder names, so a rename becomes a remove plus a create and quiz attempts are lost.
- The check has to parse macros out of prose.
- Moving to a nicer shape later means another rewrite.

## Rationale

Option 1 is chosen because the forces in Context point at it. The authors asked for mixed lessons, and a list of blocks is the only option that gives any order without adding a field per kind. The workshop will have several courses and several people editing, and a folder per course keeps their changes apart, which Option 2 does not. Keeping identity in written keys (not in file names) is what spec 0005 already does, and it protects learners' quiz attempts, so Option 4's name based identity is the wrong trade for a certificate.

You asked for one markdown kind, so `text` covers both transcripts and lab introductions; a separate `lab` name added nothing the check or the LMS would treat differently. You asked that one failing course not block the rest, so errors and failed writes are isolated per course. A write that fails in the middle of a course still stops that course only, because a rerun finds every record by key and finishes the job, which keeps spec 0005's repair story.

You first chose private images. The cross check showed this cannot work as intended: a private Frappe file is readable only by its owner or by users who can read the document it is attached to, and learners cannot read the Course Lesson in the Desk. One image shared by several lessons also attaches to only one document. Images are therefore public, with a name built from a content hash so the URL cannot be guessed. The course is already hidden by enrollment (spec 0009). The cost is that anyone holding an URL can load the image, so authors must not put secrets in images. This is a change from your earlier pick and is written down here so you can reverse it.

Two small rules were my own calls, not your answers: the folder name must equal the course key (so there is one name, not two), and a quiz that no lesson uses is a problem (it catches a mistyped path early, the same reason spec 0005 refused a quiz with no lesson). An unused guide is only a warning, so a draft can sit in git. The runner up for the image name rule was a random name; a name built from the course key and a hash was chosen because the same bytes then find the same file, which makes reruns safe without a custom field on the File record.
