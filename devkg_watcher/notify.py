"""Telegram message formatting and sending."""

from __future__ import annotations

from html import escape

import httpx

TELEGRAM_LIMIT = 4096


def format_vacancy(vacancy, relevant: bool) -> str:
    mark = "⭐ " if relevant else ""
    lines = [f'{mark}<b><a href="{escape(vacancy.url)}">{escape(vacancy.title)}</a></b>']
    head = " · ".join(p for p in (vacancy.company, vacancy.salary) if p)
    if head:
        lines.append(escape(head))
    tail = " · ".join(p for p in (vacancy.work_format, vacancy.meta) if p)
    if tail:
        lines.append(escape(tail))
    return "\n".join(lines)


def build_messages(header: str, blocks: list[str], limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Pack header + blocks into as few messages as fit Telegram's length limit."""
    messages: list[str] = []
    current = header
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                messages.append(current)
            current = block[:limit]
    if current:
        messages.append(current)
    return messages


class TelegramSender:
    def __init__(self, token: str, chat_id: str, client: httpx.Client) -> None:
        self._url = f"https://api.telegram.org/bot{token}/sendMessage"
        self._chat_id = chat_id
        self._client = client

    def send(self, text: str) -> None:
        response = self._client.post(
            self._url,
            json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            },
        )
        if response.status_code != 200:
            # Do not include the URL: it contains the bot token.
            raise RuntimeError(f"Telegram API error {response.status_code}: {response.text[:300]}")
