"""Keyword-based relevance marking."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .parser import Vacancy

# fmt: off
DEFAULT_KEYWORDS = (
    "python", "fastapi", "django", "flask",
    "backend", "back-end", "бэкенд", "бекенд",
    "fullstack", "full-stack", "full stack", "фулстек", "фуллстек",
    "react", "frontend", "front-end", "фронтенд", "javascript", "js",
    "telegram", "телеграм",
    "junior", "джуниор", "джун", "стажер", "стажёр", "стажировка", "intern",
    "postgres", "postgresql",
)

# Checked against the title only: a keyword in the description of a senior Java
# vacancy (e.g. "PostgreSQL") must not make it relevant.
DEFAULT_EXCLUDE = (
    "senior", "сеньор", "lead", "лид", "тимлид", "техлид",
    "java", "c#", ".net", "asp.net",
    "менеджер", "ассистент",
)
# fmt: on


def _word_regex(words: Iterable[str]) -> re.Pattern[str] | None:
    """Case-insensitive regex matching any of the words as a whole word."""
    unique = sorted({w.strip().lower() for w in words if w.strip()}, key=len, reverse=True)
    if not unique:
        return None
    # \w-boundaries so "js" does not match inside "jsonb", "react" not in "reactive"
    # and "java" not in "javascript".
    alternation = "|".join(re.escape(w) for w in unique)
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)


class RelevanceMatcher:
    def __init__(
        self,
        keywords: Iterable[str] = DEFAULT_KEYWORDS,
        exclude: Iterable[str] = DEFAULT_EXCLUDE,
    ) -> None:
        self._re = _word_regex(keywords)
        self._exclude_re = _word_regex(exclude)

    def matches(self, vacancy: Vacancy) -> list[str]:
        if self._re is None:
            return []
        haystack = f"{vacancy.title} {vacancy.snippet}"
        found: list[str] = []
        for m in self._re.finditer(haystack):
            word = m.group(0).lower()
            if word not in found:
                found.append(word)
        return found

    def is_excluded(self, vacancy: Vacancy) -> bool:
        return self._exclude_re is not None and self._exclude_re.search(vacancy.title) is not None

    def is_relevant(self, vacancy: Vacancy) -> bool:
        return not self.is_excluded(vacancy) and bool(self.matches(vacancy))
