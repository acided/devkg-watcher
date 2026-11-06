"""Entry point: fetch devkg job list, detect new vacancies, notify via Telegram."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable

import httpx

from .notify import TelegramSender, build_messages, format_vacancy
from .parser import BASE_URL, LIST_PATH, Vacancy, parse_page
from .relevance import DEFAULT_KEYWORDS, RelevanceMatcher
from .storage import Storage

log = logging.getLogger("devkg_watcher")

USER_AGENT = "devkg-watcher/0.1 (personal job alert script)"
MAX_PAGES = 30
REQUEST_PAUSE_SEC = 1.0
RETRIES = 3


class LayoutChangedError(RuntimeError):
    """The first list page parsed to zero vacancies: devkg markup probably changed."""


def fetch_page(client: httpx.Client, page: int) -> str:
    url = f"{BASE_URL}{LIST_PATH}?page={page}"
    for attempt in range(1, RETRIES + 1):
        try:
            response = client.get(url)
            if response.status_code < 500:
                response.raise_for_status()
                return response.text
            error: Exception = RuntimeError(f"HTTP {response.status_code} for {url}")
        except httpx.TransportError as exc:
            error = exc
        log.warning("fetch %s failed (attempt %d/%d): %s", url, attempt, RETRIES, error)
        if attempt < RETRIES:
            time.sleep(5 * attempt)
    raise error


def fetch_all(fetch: Callable[[int], str], pause: float = REQUEST_PAUSE_SEC) -> list[Vacancy]:
    """Walk list pages until an empty one; return unique vacancies in site order."""
    result: list[Vacancy] = []
    seen: set[int] = set()
    for page in range(1, MAX_PAGES + 1):
        vacancies = parse_page(fetch(page))
        if not vacancies:
            if page == 1:
                raise LayoutChangedError("page 1 has no vacancies, parser needs an update")
            break
        for v in vacancies:
            if v.id not in seen:
                seen.add(v.id)
                result.append(v)
        if pause:
            time.sleep(pause)
    else:
        log.warning("reached MAX_PAGES=%d, the list may be truncated", MAX_PAGES)
    return result


def _plural_vacancies(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "новая вакансия"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "новые вакансии"
    return "новых вакансий"


def run(
    vacancies: list[Vacancy],
    storage: Storage,
    matcher: RelevanceMatcher,
    send: Callable[[str], None],
) -> int:
    """Notify about unseen vacancies, then store them. Returns the number of new ones.

    Storing happens only after a successful send, so a failed notification is retried
    on the next run instead of being silently lost.
    """
    bootstrap = storage.is_empty()
    known = storage.known_ids(v.id for v in vacancies)
    storage.touch(known)

    new = [(v, matcher.is_relevant(v)) for v in vacancies if v.id not in known]
    if not new:
        log.info("no new vacancies (%d listed)", len(vacancies))
        return 0

    relevant = [v for v, rel in new if rel]
    if bootstrap:
        # First run: everything is "new", so send a summary plus the relevant ones only.
        header = (
            f"🟢 <b>devkg-watcher запущен</b>\n"
            f"В базе {len(new)} вакансий, релевантных сейчас: {len(relevant)}"
        )
        blocks = [format_vacancy(v, True) for v in relevant]
    else:
        ordered = sorted(new, key=lambda item: not item[1])  # relevant first, stable
        header = f"🆕 <b>devkg: {len(new)} {_plural_vacancies(len(new))}</b>"
        if relevant:
            header += f" (⭐ {len(relevant)})"
        blocks = [format_vacancy(v, rel) for v, rel in ordered]

    for message in build_messages(header, blocks):
        send(message)
    storage.add(new)
    log.info("new: %d, relevant: %d, bootstrap: %s", len(new), len(relevant), bootstrap)
    return len(new)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect new vacancies on devkg.com")
    parser.add_argument("--db", default=os.environ.get("DEVKG_DB_PATH", "devkg.sqlite3"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print messages instead of sending them and do not write to the database",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO logs leak the bot token

    env_keywords = os.environ.get("DEVKG_KEYWORDS", "")
    keywords = [k for k in env_keywords.split(",") if k.strip()] or list(DEFAULT_KEYWORDS)
    matcher = RelevanceMatcher(keywords)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not args.dry_run and not (token and chat_id):
        log.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required (or use --dry-run)")
        return 2

    if not args.dry_run:
        storage = Storage(args.db)
    elif os.path.exists(args.db):
        storage = Storage.in_memory_copy(args.db)
    else:
        storage = Storage(":memory:")

    with httpx.Client(
        timeout=30, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        if args.dry_run:

            def send(text: str) -> None:
                print(text, end="\n\n---\n\n")
        else:
            send = TelegramSender(token, chat_id, client).send

        try:
            vacancies = fetch_all(lambda page: fetch_page(client, page))
            run(vacancies, storage, matcher, send)
        except LayoutChangedError as exc:
            log.error("%s", exc)
            if not args.dry_run:
                try:
                    send(f"⚠️ <b>devkg-watcher</b>: {exc}")
                except Exception:
                    log.exception("could not send the layout alert")
            return 1
        except Exception:
            log.exception("run failed")
            return 1
        finally:
            storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
