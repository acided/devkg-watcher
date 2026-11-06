"""Keyword-based relevance marking."""

from __future__ import annotations

import re

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
# fmt: on


class RelevanceMatcher:
    def __init__(self, keywords: tuple[str, ...] | list[str] = DEFAULT_KEYWORDS) -> None:
        words = sorted({k.strip().lower() for k in keywords if k.strip()}, key=len, reverse=True)
        # \w-boundaries so "js" does not match inside "jsonb" and "react" not in "reactive".
        alternation = "|".join(re.escape(w) for w in words)
        self._re = re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE) if words else None

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

    def is_relevant(self, vacancy: Vacancy) -> bool:
        return bool(self.matches(vacancy))
