"""Интеграционные тесты TG-003: полный путь создания заявки с Telegram-скорингом.

Проверяют два сценария:
1. Заявка с telegram_channel → итоговая оценка учитывает оба источника (70/30).
2. Заявка без telegram_channel → оценка только по выписке (100% stmt).
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User, UserRole
from app.routers import applications as applications_module
from app.schemas.telegram import ParsedTelegramChannel, TelegramMessage


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# Sber-fixtura даёт stmt_score = 80 (см. test_applications.py).
_STMT_SCORE = 80


def _sber_fixture() -> bytes:
    with open(os.path.join(FIXTURES_DIR, "sber.pdf"), "rb") as fh:
        return fh.read()


class _MockDb:
    def __init__(self):
        self.added: list = []
        self.committed = False
        self.refreshed = None
        self.rolled_back = False

    def query(self, model):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def all(self):
        return []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def flush(self):
        from app.models.application import generate_application_id

        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = generate_application_id()

    def rollback(self):
        self.rolled_back = True

    def refresh(self, obj):
        self.refreshed = obj


def _current_user():
    return User(
        id=1,
        full_name="Иван Петров",
        birth_date=date(1995, 5, 20),
        login="ivan",
        password_hash="hash",
        phone="+79990000000",
        telegram="@ivan",
        role=UserRole.USER.value,
    )


def _fake_channel_data() -> ParsedTelegramChannel:
    """Фейковые данные Telegram-канала для мока fetch_channel_messages."""
    return ParsedTelegramChannel(
        username="ivan_channel",
        messages=[
            TelegramMessage(
                date=date(2026, 8, 1),
                text="Работаю над проектом, клиент доволен. Инвестиции растут.",
            ),
            TelegramMessage(
                date=date(2026, 8, 5),
                text="Отлично, получил зарплату на счёт. Бюджет в порядке.",
            ),
            TelegramMessage(
                date=date(2026, 8, 10),
                text="Фриланс, задачи, дедлайн — продуктивная неделя.",
            ),
        ],
    )


def _fake_tg_scoring_result():
    """Фейковый результат Telegram-скоринга."""
    from app.scoring.telegram_scoring import TelegramScoringResult

    return TelegramScoringResult(
        score_contribution=75,
        positive_signals=["Упоминания трудовой деятельности."],
        risk_factors=[],
        stability_score=8,
        financial_literacy_score=7,
        responsibility_score=7,
        report_content="Анализ канала @ivan_channel: 3 сообщений, ~30 слов.",
    )


class TestTG003WithTelegramChannel:
    """Заявка с telegram_channel: итоговая оценка = 70% stmt + 30% tg."""

    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.user = _current_user()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _set_db(self, db):
        app.dependency_overrides[get_db] = lambda: db

    def _set_user(self):
        app.dependency_overrides[get_current_user] = lambda: self.user

    def test_with_valid_channel(self, monkeypatch):
        """Telegram-канал доступен → оценка = 70% stmt + 30% tg."""
        db = _MockDb()
        self._set_db(db)
        self._set_user()

        monkeypatch.setattr(
            applications_module, "fetch_channel_messages", lambda ch: _fake_channel_data()
        )
        monkeypatch.setattr(applications_module, "enrich_channel_with_ocr", lambda ch, **kw: ch)
        monkeypatch.setattr(
            applications_module,
            "score_telegram_with_llm",
            lambda ch, **kw: _fake_tg_scoring_result(),
        )

        resp = self.client.post(
            "/applications",
            data={
                "amount": "50000.00",
                "purpose": "Ремонт",
                "telegram": "@ivan",
                "telegram_channel": "@ivan_channel",
            },
            files={"statement": ("sber.pdf", _sber_fixture(), "application/pdf")},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["score"] is not None

        # Формула: 80 * 0.7 + 75 * 0.3 = 56 + 22.5 = 78.5 → 78 (round).
        expected = round(_STMT_SCORE * 0.7 + 75 * 0.3)
        assert body["score"] == expected

        # ScoreResult должен содержать сигналы из обоих источников.
        score_result = db.added[1]
        assert len(score_result.positive_signals) >= 2  # stmt + tg сигналы

    def test_with_unavailable_channel(self, monkeypatch):
        """Telegram-канал недоступен → оценка только по выписке."""
        db = _MockDb()
        self._set_db(db)
        self._set_user()

        # fetch_channel_messages возвращает None (канал недоступен).
        monkeypatch.setattr(applications_module, "fetch_channel_messages", lambda ch: None)

        resp = self.client.post(
            "/applications",
            data={
                "amount": "50000.00",
                "purpose": "Ремонт",
                "telegram": "@ivan",
                "telegram_channel": "@ivan_channel",
            },
            files={"statement": ("sber.pdf", _sber_fixture(), "application/pdf")},
        )

        assert resp.status_code == 201
        body = resp.json()
        # Канал недоступен → tg_result = None → итог = 100% stmt = 80.
        assert body["score"] == _STMT_SCORE

    def test_with_empty_channel_messages(self, monkeypatch):
        """Telegram-канал доступен, но нет сообщений → оценка только по выписке."""
        db = _MockDb()
        self._set_db(db)
        self._set_user()

        empty_channel = ParsedTelegramChannel(username="ivan_channel", messages=[])
        monkeypatch.setattr(applications_module, "fetch_channel_messages", lambda ch: empty_channel)

        resp = self.client.post(
            "/applications",
            data={
                "amount": "50000.00",
                "purpose": "Ремонт",
                "telegram": "@ivan",
                "telegram_channel": "@ivan_channel",
            },
            files={"statement": ("sber.pdf", _sber_fixture(), "application/pdf")},
        )

        assert resp.status_code == 201
        body = resp.json()
        # Пустой канал (нет сообщений) → tg_result = None в пайплайне
        # → итог = 100% stmt = 80.
        assert body["score"] == _STMT_SCORE


class TestTG003WithoutTelegramChannel:
    """Заявка без telegram_channel: оценка 100% по выписке."""

    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.user = _current_user()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _set_db(self, db):
        app.dependency_overrides[get_db] = lambda: db

    def _set_user(self):
        app.dependency_overrides[get_current_user] = lambda: self.user

    def test_blank_channel_score_only_stmt(self, monkeypatch):
        """Пустой telegram_channel → Telegram не вызывается, оценка 100% stmt."""
        db = _MockDb()
        self._set_db(db)
        self._set_user()

        calls = {"fetch": 0, "ocr": 0, "llm": 0}

        def track_fetch(ch):
            calls["fetch"] += 1
            return None

        def track_ocr(ch, **kw):
            calls["ocr"] += 1
            return ch

        def track_llm(ch, **kw):
            calls["llm"] += 1
            return None

        monkeypatch.setattr(applications_module, "fetch_channel_messages", track_fetch)
        monkeypatch.setattr(applications_module, "enrich_channel_with_ocr", track_ocr)
        monkeypatch.setattr(applications_module, "score_telegram_with_llm", track_llm)

        resp = self.client.post(
            "/applications",
            data={
                "amount": "50000.00",
                "purpose": "Ремонт",
                "telegram": "@ivan",
                "telegram_channel": "",
            },
            files={"statement": ("sber.pdf", _sber_fixture(), "application/pdf")},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["score"] == _STMT_SCORE

        # Telegram-функции не вызывались.
        assert calls["fetch"] == 0
        assert calls["ocr"] == 0
        assert calls["llm"] == 0

    def test_omitted_channel_score_only_stmt(self, monkeypatch):
        """telegram_channel не передан → Telegram не вызывается."""
        db = _MockDb()
        self._set_db(db)
        self._set_user()

        def should_not_be_called(ch):
            raise AssertionError("fetch_channel_messages should not be called")

        monkeypatch.setattr(applications_module, "fetch_channel_messages", should_not_be_called)

        resp = self.client.post(
            "/applications",
            data={
                "amount": "50000.00",
                "purpose": "Ремонт",
                "telegram": "@ivan",
                "telegram_channel": None,
            },
            files={"statement": ("sber.pdf", _sber_fixture(), "application/pdf")},
        )

        assert resp.status_code == 201
        assert resp.json()["score"] == _STMT_SCORE
