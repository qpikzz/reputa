import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.application import Application, generate_application_id
from app.models.user import User, UserRole
from app.schemas.application import ApplicationCreate
from app.services.auth import create_access_token
from app.routers import applications as applications_module
from app.core.constants import (
    APPLICATION_STATUS_EMPLOYEE_APPROVED,
    APPLICATION_STATUS_EMPLOYEE_REJECTED,
    APPLICATION_STATUS_IN_QUEUE,
    MSG_STATEMENT_UNPARSABLE,
    PURPOSE_MAX_LENGTH,
    TELEGRAM_CHANNEL_MAX_LENGTH,
    ROLE_EMPLOYEE,
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _sber_fixture() -> bytes:
    with open(os.path.join(FIXTURES_DIR, "sber.pdf"), "rb") as fh:
        return fh.read()


def _mock_db(fail_commit=False):
    class FakeDb:
        def __init__(self):
            self.added = []
            self.committed = False
            self.refreshed = None
            self.rolled_back = False
            self._fail_commit = fail_commit

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
            if self._fail_commit:
                raise IntegrityError(
                    "INSERT INTO applications", {"id": "9f2a1c4e"}, Exception("UNIQUE")
                )
            self.committed = True
            for obj in self.added:
                if getattr(obj, "id", None) is None:
                    obj.id = generate_application_id()

        def flush(self):
            for obj in self.added:
                if getattr(obj, "id", None) is None:
                    obj.id = generate_application_id()

        def rollback(self):
            self.rolled_back = True

        def refresh(self, obj):
            self.refreshed = obj

    return FakeDb()


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


def _application(status=APPLICATION_STATUS_IN_QUEUE):
    return Application(
        id="a1b2c3d4e5f6",
        user_id=1,
        amount=Decimal("50000.00"),
        purpose="Ремонт квартиры",
        telegram="@ivan",
        telegram_channel="@ivan_channel",
        status=status,
    )


class _DecisionDb:
    def __init__(self, application=None):
        self.application = application
        self.committed = False
        self.refreshed = None

    def query(self, model):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.application

    def commit(self):
        self.committed = True

    def refresh(self, obj):
        self.refreshed = obj


class TestCreateApplicationEndpoint:
    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.user = _current_user()
        # Telegram-скоринг (TG-001/002/003) не должен ходить в сеть в тестах:
        # мокаем парсинг канала как недоступный → итоговая оценка только по выписке.
        self._orig_fetch = applications_module.fetch_channel_messages
        applications_module.fetch_channel_messages = lambda ch: None

    def teardown_method(self):
        app.dependency_overrides.clear()
        applications_module.fetch_channel_messages = self._orig_fetch

    def _set_db(self, db):
        app.dependency_overrides[get_db] = lambda: db

    def _set_user(self, user=None):
        app.dependency_overrides[get_current_user] = lambda: user or self.user

    def _base_data(self):
        return {
            "amount": "50000.00",
            "purpose": "Ремонт квартиры",
            "telegram": "@ivan",
            "telegram_channel": "@ivan_channel",
        }

    def _post(self, db, data=None, files=None):
        payload = self._base_data()
        if data:
            payload.update(data)
        if files is None:
            files = {"statement": ("sber.pdf", _sber_fixture(), "application/pdf")}
        return self.client.post("/applications", data=payload, files=files)

    def test_create_application_success(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db)
        assert resp.status_code == 201
        body = resp.json()
        # INFRA-004: id — случайная строка из 10-12 символов (sha256-хеш), не число.
        assert isinstance(body["id"], str)
        assert 10 <= len(body["id"]) <= 12
        assert body["user_id"] == 1
        assert body["amount"] == "50000.00"
        assert body["purpose"] == "Ремонт квартиры"
        assert body["telegram"] == "@ivan"
        assert body["telegram_channel"] == "@ivan_channel"
        assert body["status"] == APPLICATION_STATUS_IN_QUEUE
        # Канал в тесте замокан как недоступный → оценка только по выписке (STMT-002).
        assert body["score"] == 80

        assert db.committed is True
        assert len(db.added) == 2
        created = db.added[0]
        assert created.user_id == 1
        assert created.amount == Decimal("50000.00")
        assert created.status == APPLICATION_STATUS_IN_QUEUE
        score_result = db.added[1]
        assert score_result.application_id == created.id
        assert score_result.score == created.score

    def test_create_application_strips_fields(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(
            db,
            data={
                "amount": "50000.00",
                "purpose": "  Ремонт квартиры  ",
                "telegram": " @ivan ",
                "telegram_channel": " @ivan_channel ",
            },
        )
        assert resp.status_code == 201
        created = db.added[0]
        assert created.purpose == "Ремонт квартиры"
        assert created.telegram == "@ivan"
        assert created.telegram_channel == "@ivan_channel"
        assert created.score == 80

    def test_create_application_rolls_back_when_scoring_fails(self, monkeypatch):
        def fail_scoring(parsed_statement):
            raise RuntimeError("scoring failed")

        monkeypatch.setattr(applications_module, "score_statement", fail_scoring)
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db)

        assert resp.status_code == 500
        assert resp.json()["detail"] == "Не удалось рассчитать скоринг заявки"
        assert db.committed is False
        assert db.rolled_back is True

    def test_create_application_missing_statement_returns_422(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db, files={})
        assert resp.status_code == 422
        assert db.committed is False

    def test_create_application_amount_zero_returns_422(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db, data={"amount": "0"})
        assert resp.status_code == 422
        assert db.committed is False

    def test_create_application_amount_negative_returns_422(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db, data={"amount": "-100"})
        assert resp.status_code == 422
        assert db.committed is False

    def test_create_application_amount_below_min_returns_422(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db, data={"amount": "500"})
        assert resp.status_code == 422
        assert db.committed is False

    def test_create_application_amount_above_max_returns_422(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db, data={"amount": "20000000"})
        assert resp.status_code == 422
        assert db.committed is False

    def test_create_application_purpose_blank_returns_422(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db, data={"purpose": "   "})
        assert resp.status_code == 422
        assert db.committed is False

    def test_create_application_purpose_too_long_returns_422(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db, data={"purpose": "x" * (PURPOSE_MAX_LENGTH + 1)})
        assert resp.status_code == 422
        assert db.committed is False

    def test_create_application_telegram_no_at_returns_422(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db, data={"telegram": "ivan"})
        assert resp.status_code == 422
        assert db.committed is False

    def test_create_application_channel_blank_accepted(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db, data={"telegram_channel": ""})
        assert resp.status_code == 201
        assert db.added[0].telegram_channel == ""

    def test_create_application_channel_omitted_accepted(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db, data={"telegram_channel": None})
        assert resp.status_code == 201
        assert db.added[0].telegram_channel == ""

    def test_create_application_channel_too_long_returns_422(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(db, data={"telegram_channel": "@" + "c" * TELEGRAM_CHANNEL_MAX_LENGTH})
        assert resp.status_code == 422
        assert db.committed is False

    def test_create_application_statement_too_large_returns_413(self, monkeypatch):
        monkeypatch.setattr(applications_module, "STATEMENT_MAX_SIZE_BYTES", 100)
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(
            db,
            files={"statement": ("big.pdf", b"x" * 101, "application/pdf")},
        )
        assert resp.status_code == 413
        assert db.committed is False

    def test_create_application_unparseable_statement_returns_422(self):
        db = _mock_db()
        self._set_db(db)
        self._set_user()

        resp = self._post(
            db,
            files={"statement": ("garbage.pdf", b"not a pdf at all", "application/pdf")},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"] == MSG_STATEMENT_UNPARSABLE
        assert db.committed is False
        assert db.added == []

    def test_create_application_unauthenticated_returns_401(self):
        db = _mock_db()
        self._set_db(db)

        resp = self._post(db)
        assert resp.status_code == 401
        assert db.committed is False
        assert db.added == []

    def test_create_application_invalid_token_returns_401(self):
        db = _mock_db()
        self._set_db(db)
        self.client.cookies.set("access_token", "not-a-jwt")

        resp = self._post(db)
        assert resp.status_code == 401
        assert db.committed is False

    def test_create_application_unknown_user_returns_401(self):
        db = _mock_db()
        self._set_db(db)
        # Токен выпускается для пользователя, которого нет в БД (и которого
        # не вернёт fake-БД) — реальная зависимость get_current_user даёт 401.
        ghost = User(
            id=999,
            full_name="Призрак",
            birth_date=date(1995, 5, 20),
            login="ghost",
            password_hash="hash",
            phone="+79990000000",
            telegram="@ghost",
            role=UserRole.USER.value,
        )
        self.client.cookies.set("access_token", create_access_token(ghost))

        resp = self._post(db)
        assert resp.status_code == 401
        assert db.committed is False


class TestApplicationCreateValidation:
    def test_valid_application_create(self):
        req = ApplicationCreate(
            amount=Decimal("50000.00"),
            purpose="Ремонт квартиры",
            telegram="@ivan",
            telegram_channel="@ivan_channel",
        )
        assert req.amount == Decimal("50000.00")
        assert req.purpose == "Ремонт квартиры"
        assert req.telegram == "@ivan"
        assert req.telegram_channel == "@ivan_channel"

    def test_amount_zero_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreate(
                amount=Decimal("0"),
                purpose="Ремонт",
                telegram="@ivan",
                telegram_channel="@ivan_channel",
            )

    def test_amount_negative_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreate(
                amount=Decimal("-1"),
                purpose="Ремонт",
                telegram="@ivan",
                telegram_channel="@ivan_channel",
            )

    def test_amount_below_min_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreate(
                amount=Decimal("500"),
                purpose="Ремонт",
                telegram="@ivan",
                telegram_channel="@ivan_channel",
            )

    def test_amount_above_max_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreate(
                amount=Decimal("20000000"),
                purpose="Ремонт",
                telegram="@ivan",
                telegram_channel="@ivan_channel",
            )

    def test_purpose_blank_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreate(
                amount=Decimal("1000"),
                purpose="  ",
                telegram="@ivan",
                telegram_channel="@ivan_channel",
            )

    def test_telegram_without_at_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreate(
                amount=Decimal("1000"),
                purpose="Ремонт",
                telegram="ivan",
                telegram_channel="@ivan_channel",
            )

    def test_telegram_channel_blank_accepted(self):
        req = ApplicationCreate(
            amount=Decimal("1000"),
            purpose="Ремонт",
            telegram="@ivan",
            telegram_channel="",
        )
        assert req.telegram_channel == ""

    def test_telegram_channel_without_at_rejected(self):
        with pytest.raises(ValidationError):
            ApplicationCreate(
                amount=Decimal("1000"),
                purpose="Ремонт",
                telegram="@ivan",
                telegram_channel="ivan_channel",
            )


class TestApplicationDecisionEndpoint:
    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.employee = _current_user()
        self.employee.role = ROLE_EMPLOYEE

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _set_dependencies(self, db, user=None):
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: user or self.employee

    def test_employee_approves_application(self):
        application = _application()
        db = _DecisionDb(application)
        self._set_dependencies(db)
        response = self.client.post("/applications/a1b2c3d4e5f6/decision", json={"decision": "approve"})
        assert response.status_code == 200
        assert response.json()["status"] == APPLICATION_STATUS_EMPLOYEE_APPROVED
        assert application.status == APPLICATION_STATUS_EMPLOYEE_APPROVED
        assert application.decided_by == 1
        assert db.committed is True
        assert db.refreshed is application

    def test_employee_rejects_application(self):
        application = _application()
        db = _DecisionDb(application)
        self._set_dependencies(db)
        response = self.client.post("/applications/a1b2c3d4e5f6/decision", json={"decision": "reject"})
        assert response.status_code == 200
        assert response.json()["status"] == APPLICATION_STATUS_EMPLOYEE_REJECTED
        assert application.decided_by == 1

    def test_user_cannot_decide_application(self):
        db = _DecisionDb(_application())
        self._set_dependencies(db, _current_user())
        response = self.client.post("/applications/a1b2c3d4e5f6/decision", json={"decision": "approve"})
        assert response.status_code == 403
        assert db.committed is False

    def test_decision_for_missing_application_returns_404(self):
        db = _DecisionDb()
        self._set_dependencies(db)
        response = self.client.post("/applications/a1b2c3d4e5f6/decision", json={"decision": "approve"})
        assert response.status_code == 404
        assert db.committed is False

    def test_decision_for_already_decided_application_returns_409(self):
        db = _DecisionDb(_application(APPLICATION_STATUS_EMPLOYEE_APPROVED))
        self._set_dependencies(db)
        response = self.client.post("/applications/a1b2c3d4e5f6/decision", json={"decision": "reject"})
        assert response.status_code == 409
        assert db.committed is False

    def test_invalid_decision_returns_422(self):
        db = _DecisionDb(_application())
        self._set_dependencies(db)
        response = self.client.post("/applications/a1b2c3d4e5f6/decision", json={"decision": "maybe"})
        assert response.status_code == 422
        assert db.committed is False