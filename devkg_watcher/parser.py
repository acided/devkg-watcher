"""Parse devkg.com job list pages into Vacancy objects."""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

BASE_URL = "https://devkg.com"
LIST_PATH = "/ru/rabota"

_ID_RE = re.compile(r"-(\d+)$")
_SEPARATORS = {"·", ""}


@dataclass(frozen=True)
class Vacancy:
    id: int
    url: str
    title: str
    company: str
    salary: str
    snippet: str
    work_format: str  # "В офисе" / "Удалённо" / "Гибрид" or ""
    meta: str  # e.g. "Опыт 2–5 лет · Полный день" or ""


def _text(tag: Tag | None) -> str:
    if tag is None:
        return ""
    return " ".join(tag.get_text(" ", strip=True).split())


def _parse_salary(tag: Tag | None) -> str:
    if tag is None:
        return ""
    # Drop the decorative "с" (som glyph); the screen-reader "KGS" stays.
    for hidden in tag.select('[aria-hidden="true"]'):
        hidden.decompose()
    return _text(tag)


def _parse_card(a: Tag) -> Vacancy | None:
    href = a.get("href", "")
    match = _ID_RE.search(href)
    if not match:
        return None

    title = _text(a.select_one("span.mt-1"))
    if not title:
        return None

    company = _text(a.select_one("span.truncate.font-semibold"))
    work_format = _text(a.select_one("span.h-6.rounded-full"))

    meta = ""
    row = a.select_one("span.mt-3")
    if row is not None:
        for child in row.find_all("span", recursive=False):
            classes = child.get("class") or []
            if "rounded-full" in classes or child.select_one('[data-slot="avatar"]'):
                continue  # format chip or company block
            text = _text(child)
            if text not in _SEPARATORS:
                meta = text

    return Vacancy(
        id=int(match.group(1)),
        url=BASE_URL + href,
        title=title,
        company=company,
        salary=_parse_salary(a.select_one("span.tabular-nums")),
        snippet=_text(a.select_one("span.line-clamp-2")),
        work_format=work_format,
        meta=meta,
    )


def parse_page(html: str) -> list[Vacancy]:
    """Return vacancies from one list page in page order, without duplicates."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[int] = set()
    result: list[Vacancy] = []
    for a in soup.select('a[href^="/ru/vakansiya-"]'):
        vacancy = _parse_card(a)
        if vacancy is not None and vacancy.id not in seen:
            seen.add(vacancy.id)
            result.append(vacancy)
    return result
