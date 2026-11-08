from pathlib import Path

import pytest

from devkg_watcher.main import LayoutChangedError, fetch_all, run
from devkg_watcher.notify import build_messages, format_vacancy
from devkg_watcher.parser import Vacancy, parse_page
from devkg_watcher.relevance import RelevanceMatcher
from devkg_watcher.storage import Storage

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


def make_vacancy(id: int, title: str = "Python developer", snippet: str = "") -> Vacancy:
    return Vacancy(
        id=id,
        url=f"https://devkg.com/ru/vakansiya-x-{id}",
        title=title,
        company="ACME",
        salary="от 100 000 KGS",
        snippet=snippet,
        work_format="Удалённо",
        meta="",
    )


# --- parser -----------------------------------------------------------------


def test_parse_full_page():
    vacancies = parse_page(load("page_full"))
    assert len(vacancies) == 20
    assert len({v.id for v in vacancies}) == 20
    assert all(
        v.title and v.company and v.url.startswith("https://devkg.com/ru/vakansiya-")
        for v in vacancies
    )


def test_parse_card_fields():
    by_id = {v.id: v for v in parse_page(load("page_full"))}
    v = by_id[32083]
    assert v.title == "Fullstack-разработчик"
    assert v.company == "Yaros Group"
    assert v.salary == "от 100 000 KGS"
    assert v.work_format == "В офисе"
    assert v.meta == "Опыт от 5 лет · Полный день"
    assert v.url == "https://devkg.com/ru/vakansiya-fullstack-razrabotchik-yaros-group-32083"
    assert by_id[32092].salary == "от 2 000 USD"
    assert by_id[22785].meta == ""  # card without experience/schedule line


def test_parse_last_and_empty_pages():
    assert len(parse_page(load("page_last"))) == 11
    assert parse_page(load("page_empty")) == []


# --- fetching ---------------------------------------------------------------


def test_fetch_all_walks_until_empty_page():
    pages = {1: load("page_full"), 2: load("page_last"), 3: load("page_empty")}
    requested = []

    def fetch(page):
        requested.append(page)
        return pages[page]

    assert len(fetch_all(fetch, pause=0)) == 31
    assert requested == [1, 2, 3]


def test_fetch_all_raises_when_first_page_is_empty():
    with pytest.raises(LayoutChangedError):
        fetch_all(lambda page: load("page_empty"), pause=0)


# --- relevance --------------------------------------------------------------


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Fullstack-разработчик", True),
        ("Full-Stack разработчик", True),
        ("Middle applied AI / LLM Engineer (Python)", True),
        ("Ментор стажировочной программы JS/TS", True),
        ("Бухгалтер", False),
        ("Reactive systems engineer", False),  # "react" must not match inside a word
        ("JSONB expert", False),
    ],
)
def test_relevance(title, expected):
    assert RelevanceMatcher().is_relevant(make_vacancy(1, title=title)) is expected


@pytest.mark.parametrize(
    "title, snippet, expected",
    [
        ("Senior C#/.NET разработчик / Tech Lead", "Backend, PostgreSQL", False),
        ("Backend Java Developer", "", False),
        ("Java-разработчик", "PostgreSQL", False),
        ("Senior Backend-разработчик (NodeJS)", "", False),
        ("Менеджер по развитию бизнеса (B2B SaaS / AI / Automation)", "Telegram", False),
        ("Стажер ассистент руководителя удаленно", "", False),
        ("JavaScript Developer / Vibe Coding Mentor", "", True),  # "java" not in "javascript"
        ("ASP.NET разработчик", "", False),
        ("Python разработчик (Middle+)", "", True),
        ("Разработчик", "Python, FastAPI", True),  # keyword only in the description
    ],
)
def test_relevance_exclude_by_title(title, snippet, expected):
    vacancy = make_vacancy(1, title=title, snippet=snippet)
    assert RelevanceMatcher().is_relevant(vacancy) is expected


def test_exclude_word_in_snippet_does_not_exclude():
    vacancy = make_vacancy(1, title="Python developer", snippet="работа с senior командой на Java")
    assert RelevanceMatcher().is_relevant(vacancy)


def test_relevance_custom_exclude():
    matcher = RelevanceMatcher(exclude=["middle"])
    assert not matcher.is_relevant(make_vacancy(1, title="Middle Python developer"))
    assert matcher.is_relevant(make_vacancy(1, title="Senior Python developer"))


def test_relevance_custom_keywords():
    matcher = RelevanceMatcher(["golang"])
    assert matcher.is_relevant(make_vacancy(1, title="Golang dev"))
    assert not matcher.is_relevant(make_vacancy(1, title="Python dev"))


# --- notification -----------------------------------------------------------


def test_format_escapes_html():
    text = format_vacancy(make_vacancy(1, title="C# <Senior> & Lead"), relevant=True)
    assert text.startswith("⭐ ")
    assert "C# &lt;Senior&gt; &amp; Lead" in text


def test_build_messages_respects_limit():
    blocks = ["x" * 1000 for _ in range(10)]
    messages = build_messages("header", blocks, limit=4096)
    assert all(len(m) <= 4096 for m in messages)
    assert len(messages) == 3
    assert sum(m.count("x" * 1000) for m in messages) == 10


# --- run --------------------------------------------------------------------


@pytest.fixture
def storage():
    s = Storage(":memory:")
    yield s
    s.close()


def test_first_run_bootstraps_with_relevant_only(storage):
    sent = []
    vacancies = [make_vacancy(1), make_vacancy(2, title="Бухгалтер")]
    assert run(vacancies, storage, RelevanceMatcher(), sent.append) == 2
    assert len(sent) == 1
    assert "запущен" in sent[0]
    assert "Python developer" in sent[0] and "Бухгалтер" not in sent[0]


def test_second_run_reports_only_new_relevant_first(storage):
    run([make_vacancy(1)], storage, RelevanceMatcher(), lambda _: None)
    sent = []
    vacancies = [
        make_vacancy(1),
        make_vacancy(3, title="Бухгалтер"),
        make_vacancy(2, title="React dev"),
    ]
    assert run(vacancies, storage, RelevanceMatcher(), sent.append) == 2
    assert len(sent) == 1
    assert "2 новые вакансии" in sent[0]
    assert sent[0].index("React dev") < sent[0].index("Бухгалтер")

    assert run(vacancies, storage, RelevanceMatcher(), sent.append) == 0
    assert len(sent) == 2  # nothing new: a heartbeat message only
    assert "новых вакансий не появилось" in sent[1]
    assert "на сайте 3" in sent[1]


def test_failed_send_keeps_vacancies_unseen(storage):
    run([make_vacancy(1)], storage, RelevanceMatcher(), lambda _: None)

    def broken_send(_):
        raise RuntimeError("telegram down")

    with pytest.raises(RuntimeError):
        run([make_vacancy(1), make_vacancy(2)], storage, RelevanceMatcher(), broken_send)

    sent = []
    assert run([make_vacancy(1), make_vacancy(2)], storage, RelevanceMatcher(), sent.append) == 1
    assert len(sent) == 1


# --- main -------------------------------------------------------------------


def test_main_alerts_on_unexpected_failure(monkeypatch, tmp_path):
    import devkg_watcher.main as main_module

    sent = []

    class FakeSender:
        def __init__(self, token, chat_id, client):
            pass

        def send(self, text):
            sent.append(text)

    def broken_fetch_all(_fetch):
        raise RuntimeError("devkg <down> for SECRET-TOKEN")

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "SECRET-TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(main_module, "TelegramSender", FakeSender)
    monkeypatch.setattr(main_module, "fetch_all", broken_fetch_all)

    assert main_module.main(["--db", str(tmp_path / "db.sqlite3")]) == 1
    assert len(sent) == 1
    assert "запуск упал: RuntimeError" in sent[0]
    assert "&lt;down&gt;" in sent[0]
    assert "SECRET-TOKEN" not in sent[0]
