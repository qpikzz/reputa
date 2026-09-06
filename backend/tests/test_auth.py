import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.auth import RegisterRequest
from app.core.constants import (
    PASSWORD_MIN_LENGTH,
    PASSWORD_MAX_LENGTH,
    MSG_INVALID_CREDENTIALS,
    MSG_INVALID_STAFF_CODE,
    MSG_NOT_EMPLOYEE,
    MSG_EMPLOYEE_LOGIN_FORBIDDEN,
    STAFF_LOGIN_CODE,
    PASSWORD_RESET_CODE,
    MSG_PASSWORD_RESET_CODE_SENT,
    MSG_INVALID_PASSWORD_RESET_CODE,
    MSG_PASSWORD_RESET_SUCCESS,
)
from app.services.auth import create_access_token, hash_password, verify_password


def _mock_db(existing_login=None, fail_commit=False, password_hash="x", role=UserRole.USER.value, count=1):
    class FakeDb:
        def __init__(self, existing_login):
            self._existing_login = existing_login
            self._password_hash = password_hash
            self._role = role
            self._count = count
            self.added = []
            self.committed = False
            self.refreshed = None
            self.rolled_back = False
            self._fail_commit = fail_commit

        def query(self, model):
            self._query_model = model
            return self

        def filter(self, *args, **kwargs):
            return self

        def count(self):
            return self._count

        def first(self):
            if self._existing_login is not None:
                if hasattr(self, "_user"):
                    return self._user
                user = User(
                    id=1,
                    full_name="Иван",
                    birth_date=date(1995, 1, 1),
                    login=self._existing_login,
                    password_hash=self._password_hash,
                    phone="+79990000000",
                    telegram="@ivan",
                    role=self._role,
                )
                self._user = user
                return user
            return None

        def add(self, obj):
            self.added.append(obj)

        def commit(self):
            if self._fail_commit:
                raise IntegrityError("INSERT INTO users", {"login": "ivan"}, Exception("UNIQUE"))
            self.committed = True
            for obj in self.added:
                obj.id = 1 if getattr(obj, "id", None) is None else obj.id

        def rollback(self):
            self.rolled_back = True

        def refresh(self, obj):
            self.refreshed = obj

    return FakeDb(existing_login)


def _valid_payload(**overrides):
    data = {
        "full_name": "Иван Петров",
        "birth_date": "1995-05-20",
        "login": "ivan",
        "password": "Abcdef1!",
        "phone": "+79990000000",
        "telegram": "@ivan",
    }
    data.update(overrides)
    return data


class TestRegistrationEndpoint:
    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self._overrides_cleared = False

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _set_db(self, db):
        app.dependency_overrides[get_db] = lambda: db

    def test_register_success(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload())
        assert resp.status_code == 201
        body = resp.json()
        assert body["login"] == "ivan"
        assert body["full_name"] == "Иван Петров"
        assert body["role"] == UserRole.USER.value
        assert body["id"] == 1
        assert db.committed is True
        assert len(db.added) == 1
        assert db.added[0].password_hash != "Abcdef1!"

    def test_register_duplicate_login(self):
        db = _mock_db(existing_login="ivan")
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload())
        assert resp.status_code == 409
        assert db.committed is False

    def test_register_password_too_short(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload(password="Ab1!"))
        assert resp.status_code == 422
        assert db.committed is False

    def test_register_password_too_long(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        long_pw = "A" + "b" * (PASSWORD_MAX_LENGTH - 1) + "1!"
        resp = self.client.post("/auth/register", json=_valid_payload(password=long_pw))
        assert resp.status_code == 422
        assert db.committed is False

    def test_register_password_no_uppercase(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload(password="abcdef1!"))
        assert resp.status_code == 422

    def test_register_password_no_lowercase(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload(password="ABCDEF1!"))
        assert resp.status_code == 422

    def test_register_password_no_digit(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload(password="Abcdefg!"))
        assert resp.status_code == 422

    def test_register_password_no_special(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload(password="Abcdefg1"))
        assert resp.status_code == 422

    def test_register_invalid_phone(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload(phone="abc"))
        assert resp.status_code == 422

    def test_register_telegram_no_at(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload(telegram="ivan"))
        assert resp.status_code == 422

    def test_register_empty_full_name(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload(full_name=""))
        assert resp.status_code == 422

    def test_register_empty_login(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload(login=""))
        assert resp.status_code == 422

    def test_register_race_duplicate_returns_409(self):
        db = _mock_db(existing_login=None, fail_commit=True)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload())
        assert resp.status_code == 409
        assert db.rolled_back is True

    def test_register_future_birth_date(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload(birth_date="2050-01-01"))
        assert resp.status_code == 422
        assert db.committed is False

    def test_register_too_old_birth_date(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register", json=_valid_payload(birth_date="1800-01-01"))
        assert resp.status_code == 422
        assert db.committed is False


class TestEmployeeRegisterEndpoint:
    """Регистрация сотрудника (AUTH-010): роль employee + валидация идентификатора."""

    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _set_db(self, db):
        app.dependency_overrides[get_db] = lambda: db

    def _valid_payload(self, **overrides):
        data = _valid_payload(identifier="A123room19")
        data.pop("identifier", None)
        data["identifier"] = "A123room19"
        data.update(overrides)
        return data

    def test_register_employee_success(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register/employee", json=self._valid_payload())
        assert resp.status_code == 201
        body = resp.json()
        assert body["login"] == "ivan"
        assert body["role"] == UserRole.EMPLOYEE.value
        assert body["id"] == 1
        assert db.committed is True
        assert len(db.added) == 1
        assert db.added[0].role == UserRole.EMPLOYEE.value
        assert db.added[0].password_hash != "Abcdef1!"

    def test_register_employee_always_employee_even_if_users_exist(self):
        # В отличие от обычной регистрации, bootstrap-правило не применяется:
        # роль employee задаётся явно, даже когда в БД уже есть пользователи.
        db = _mock_db(existing_login=None, count=1)
        self._set_db(db)

        resp = self.client.post("/auth/register/employee", json=self._valid_payload())
        assert resp.status_code == 201
        assert resp.json()["role"] == UserRole.EMPLOYEE.value

    def test_register_employee_invalid_identifier(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        for bad in ("123room19", "A12room19", "A1234room19", "AA23room19", "a123ROOM19", "A123room18"):
            resp = self.client.post("/auth/register/employee", json=self._valid_payload(identifier=bad))
            assert resp.status_code == 422, f"identifer {bad!r} должен отклоняться"
            assert db.committed is False

    def test_register_employee_empty_identifier(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        resp = self.client.post("/auth/register/employee", json=self._valid_payload(identifier=""))
        assert resp.status_code == 422
        assert db.committed is False

    def test_register_employee_valid_identifiers(self):
        db = _mock_db(existing_login=None)
        self._set_db(db)

        for ok in ("A123room19", "z999room19", "Z000room19", "b123room19"):
            resp = self.client.post("/auth/register/employee", json=self._valid_payload(identifier=ok))
            assert resp.status_code == 201, f"identifer {ok!r} должен проходить"
            assert resp.json()["role"] == UserRole.EMPLOYEE.value

    def test_register_employee_duplicate_login(self):
        db = _mock_db(existing_login="ivan")
        self._set_db(db)

        resp = self.client.post("/auth/register/employee", json=self._valid_payload())
        assert resp.status_code == 409
        assert db.committed is False

    def test_register_employee_race_duplicate_returns_409(self):
        db = _mock_db(existing_login=None, fail_commit=True)
        self._set_db(db)

        resp = self.client.post("/auth/register/employee", json=self._valid_payload())
        assert resp.status_code == 409
        assert db.rolled_back is True


class TestPasswordValidation:
    def test_valid_password_accepted(self):
        req = RegisterRequest(
            full_name="Test",
            birth_date=date(2000, 1, 1),
            login="test",
            password="Abcdef1!",
            phone="+79990000000",
            telegram="@test",
        )
        assert req.password == "Abcdef1!"

    def test_min_length_rejected(self):
        pw = "A" * (PASSWORD_MIN_LENGTH - 1) + "1!"
        with pytest.raises(ValidationError):
            RegisterRequest(
                full_name="Test",
                birth_date=date(2000, 1, 1),
                login="test",
                password=pw,
                phone="+79990000000",
                telegram="@test",
            )

    def test_max_length_rejected(self):
        pw = "Aa1!" + "x" * PASSWORD_MAX_LENGTH
        with pytest.raises(ValidationError):
            RegisterRequest(
                full_name="Test",
                birth_date=date(2000, 1, 1),
                login="test",
                password=pw,
                phone="+79990000000",
                telegram="@test",
            )


class TestLoginEndpoint:
    PASSWORD = "Abcdef1!"

    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self._db = _mock_db(
            existing_login="ivan",
            password_hash=hash_password(self.PASSWORD),
        )
        app.dependency_overrides[get_db] = lambda: self._db

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _post(self, **overrides):
        payload = {"login": "ivan", "password": self.PASSWORD}
        payload.update(overrides)
        return self.client.post("/auth/login", json=payload)

    def test_login_success_sets_http_only_cookie(self):
        resp = self._post()
        assert resp.status_code == 200
        body = resp.json()
        assert body["login"] == "ivan"
        assert body["role"] == UserRole.USER.value
        set_cookie = resp.headers.get("set-cookie", "")
        assert "access_token=" in set_cookie
        assert "HttpOnly" in set_cookie
        token = resp.cookies.get("access_token")
        assert token

    def test_login_returns_valid_jwt(self):
        resp = self._post()
        token = resp.cookies.get("access_token")
        from app.core.config import settings
        import jwt

        claims = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        assert claims["sub"] == "1"
        assert claims["role"] == UserRole.USER.value

    def test_login_trims_login_like_registration(self):
        resp = self._post(login="  ivan  ")
        assert resp.status_code == 200

    def test_login_wrong_password(self):
        resp = self._post(password="WrongPass1!")
        assert resp.status_code == 401
        assert resp.json()["detail"] == MSG_INVALID_CREDENTIALS
        assert "access_token" not in resp.cookies

    def test_login_unknown_login(self):
        db = _mock_db(existing_login=None)
        app.dependency_overrides[get_db] = lambda: db
        resp = self._post(login="nobody")
        assert resp.status_code == 401
        assert resp.json()["detail"] == MSG_INVALID_CREDENTIALS

    def test_login_empty_login(self):
        resp = self._post(login="")
        assert resp.status_code == 422

    def test_login_empty_password(self):
        resp = self._post(password="")
        assert resp.status_code == 422

    def test_login_employee_forbidden(self):
        # AUTH-009: сотрудник не входит через обычный /login, даже с верными
        # логином и паролем — ему доступен только /auth/login/employee.
        db = _mock_db(
            existing_login="ivan",
            password_hash=hash_password(self.PASSWORD),
            role=UserRole.EMPLOYEE.value,
        )
        app.dependency_overrides[get_db] = lambda: db
        resp = self._post()
        assert resp.status_code == 403
        assert resp.json()["detail"] == MSG_EMPLOYEE_LOGIN_FORBIDDEN
        assert "access_token" not in resp.cookies


class TestPasswordResetEndpoint:
    PASSWORD = "Abcdef1!"

    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.db = _mock_db(existing_login="ivan", password_hash=hash_password(self.PASSWORD))
        app.dependency_overrides[get_db] = lambda: self.db

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_request_returns_generic_success_message(self):
        response = self.client.post("/auth/password-reset/request", json={"identifier": "ivan"})

        assert response.status_code == 200
        assert response.json()["message"] == MSG_PASSWORD_RESET_CODE_SENT

    def test_confirm_rejects_invalid_code(self):
        response = self.client.post(
            "/auth/password-reset/confirm",
            json={"identifier": "ivan", "code": "000000", "password": "Newpass1!"},
        )

        assert response.status_code == 401
        assert response.json()["detail"] == MSG_INVALID_PASSWORD_RESET_CODE

    def test_confirm_updates_password_hash(self):
        response = self.client.post(
            "/auth/password-reset/confirm",
            json={"identifier": "ivan", "code": PASSWORD_RESET_CODE, "password": "Newpass1!"},
        )

        assert response.status_code == 200
        assert response.json()["message"] == MSG_PASSWORD_RESET_SUCCESS
        assert self.db.committed is True
        assert verify_password("Newpass1!", self.db.first().password_hash)


class TestCreateAccessToken:
    def test_token_contains_user_identity_and_expiry(self):
        import jwt
        from datetime import datetime, timedelta, timezone

        from app.core.config import settings

        user = User(
            id=7,
            full_name="Иван",
            birth_date=date(1995, 1, 1),
            login="ivan",
            password_hash="x",
            phone="+79990000000",
            telegram="@ivan",
            role=UserRole.USER.value,
        )
        token = create_access_token(user)
        claims = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        assert claims["sub"] == "7"
        assert claims["role"] == UserRole.USER.value
        exp = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
        lifetime = exp - datetime.fromtimestamp(claims["iat"], tz=timezone.utc)
        assert lifetime == timedelta(minutes=settings.JWT_EXPIRE_MINUTES)


class TestRegisterBootstrap:
    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_register_first_user_in_empty_db_is_employee(self):
        db = _mock_db(existing_login=None, count=0)
        app.dependency_overrides[get_db] = lambda: db
        resp = self.client.post("/auth/register", json=_valid_payload())
        assert resp.status_code == 201
        assert resp.json()["role"] == UserRole.EMPLOYEE.value

    def test_register_when_users_exist_is_regular_user(self):
        db = _mock_db(existing_login=None, count=1)
        app.dependency_overrides[get_db] = lambda: db
        resp = self.client.post("/auth/register", json=_valid_payload())
        assert resp.status_code == 201
        assert resp.json()["role"] == UserRole.USER.value


class TestEmployeeLoginEndpoint:
    PASSWORD = "Abcdef1!"

    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self._db = _mock_db(
            existing_login="ivan",
            password_hash=hash_password(self.PASSWORD),
            role=UserRole.EMPLOYEE.value,
        )
        app.dependency_overrides[get_db] = lambda: self._db

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _post(self, **overrides):
        payload = {"login": "ivan", "code": STAFF_LOGIN_CODE, "password": self.PASSWORD}
        payload.update(overrides)
        return self.client.post("/auth/login/employee", json=payload)

    def test_employee_login_success_sets_http_only_cookie(self):
        resp = self._post()
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == UserRole.EMPLOYEE.value
        set_cookie = resp.headers.get("set-cookie", "")
        assert "access_token=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert resp.cookies.get("access_token")

    def test_employee_login_returns_employee_jwt(self):
        import jwt

        from app.core.config import settings

        resp = self._post()
        token = resp.cookies.get("access_token")
        claims = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        assert claims["sub"] == "1"
        assert claims["role"] == UserRole.EMPLOYEE.value

    def test_employee_login_trims_login_like_registration(self):
        resp = self._post(login="  ivan  ")
        assert resp.status_code == 200

    def test_employee_login_wrong_code(self):
        resp = self._post(code="000000")
        assert resp.status_code == 401
        assert resp.json()["detail"] == MSG_INVALID_STAFF_CODE
        assert "access_token" not in resp.cookies

    def test_employee_login_wrong_password(self):
        resp = self._post(password="WrongPass1!")
        assert resp.status_code == 401
        assert resp.json()["detail"] == MSG_INVALID_CREDENTIALS

    def test_employee_login_unknown_login(self):
        db = _mock_db(existing_login=None, password_hash="x")
        app.dependency_overrides[get_db] = lambda: db
        resp = self._post(login="nobody")
        assert resp.status_code == 401
        assert resp.json()["detail"] == MSG_INVALID_CREDENTIALS

    def test_employee_login_forbidden_for_regular_user(self):
        db = _mock_db(
            existing_login="ivan",
            password_hash=hash_password(self.PASSWORD),
            role=UserRole.USER.value,
        )
        app.dependency_overrides[get_db] = lambda: db
        resp = self._post()
        assert resp.status_code == 403
        assert resp.json()["detail"] == MSG_NOT_EMPLOYEE

    def test_employee_login_code_first(self):
        # Неверный код отбивается до запросов к БД: пользователя даже не ищем.
        db = _mock_db(existing_login="ivan", password_hash="x")
        app.dependency_overrides[get_db] = lambda: db
        resp = self._post(code="000000")
        assert resp.status_code == 401
        assert resp.json()["detail"] == MSG_INVALID_STAFF_CODE

    def test_employee_login_empty_code(self):
        resp = self._post(code="")
        assert resp.status_code == 422

    def test_employee_login_empty_password(self):
        resp = self._post(password="")
        assert resp.status_code == 422
