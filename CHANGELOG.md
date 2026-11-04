# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Content sync: `make tools CMD=sync` builds the Nile Workshop course in the LMS from files in git. `content/course.yaml` holds the chapters, lessons (video, lab guide or quiz) and the quizzes with their multiple choice questions. `content/labs/*.md` holds the lab guides. Running it again updates the same records and creates no duplicates (see spec 0005).
- `make tools CMD="sync --check"` lists what would change, writes nothing, and exits 1 if anything differs. It also lists lessons added by hand in the Desk.
- The sync checks the content files first and reports every problem in one run, naming the file and the key, before it writes anything.
- When a request to the LMS fails, the sync stops and prints the record, the URL, the HTTP status and the reason, without a traceback and without any secret.
- Every existing batch gets the course added once, and student progress is recalculated when the course outline changes.
- Tests for the sync: unit tests with a fake LMS, and live integration tests that build a throwaway course and a throwaway student on the running site, then delete them.

### Changed
- Git wins over the LMS. If a synced record was edited in the Desk, `sync` prints `LMS has X, git has Y` and overwrites it. Run `--check` first to see those edits.
- Nothing is deleted. A lesson, chapter, quiz or question removed from git leaves the course outline and stays in the LMS, and the command names each one it detaches.
