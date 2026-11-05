"""Small builders for the block model, so a test can say what a lesson holds in one line."""

from nile_tools.content import Lesson, QuizBlock, TextBlock, VideoBlock


def VideoLesson(key: str, title: str, youtube: str) -> Lesson:
    return Lesson(key, title, (VideoBlock(youtube),))


def QuizLesson(key: str, title: str, quiz_key: str) -> Lesson:
    return Lesson(key, title, (QuizBlock(quiz_key),))


def LabLesson(key: str, title: str, body: str) -> Lesson:
    return Lesson(key, title, (TextBlock(f"guides/{key}.md", body),))
