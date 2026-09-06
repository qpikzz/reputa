from datetime import date
import re

from pydantic import BaseModel, field_validator

from app.core.constants import (
    EMPLOYEE_IDENTIFIER_PATTERN,
    FULL_NAME_MAX_LENGTH,
    LOGIN_MAX_LENGTH,
    USER_MAX_AGE_YEARS,
)
from app.schemas.validators import (
    _strip_required,
    validate_password,
    validate_phone,
    validate_telegram,
)


class RegisterRequestBase(BaseModel):
    """Общие поля и валидация для регистрации (обычной и сотрудника).

    Отдельная база нужна, чтобы эндпоинт сотрудника (AUTH-010) переиспользовал
    одинаковую валидацию ФИО/даты/логина/пароля/телефона/телеграма, не дублируя
    код, и добавлял только своё поле идентификатора.
    """

    full_name: str
    birth_date: date
    login: str
    password: str
    phone: str
    telegram: str

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        v = _strip_required(v, "ФИО не может быть пустым")
        if len(v) > FULL_NAME_MAX_LENGTH:
            raise ValueError(f"ФИО не может превышать {FULL_NAME_MAX_LENGTH} символов")
        return v

    @field_validator("login")
    @classmethod
    def validate_login(cls, v: str) -> str:
        v = _strip_required(v, "Логин не может быть пустым")
        if len(v) > LOGIN_MAX_LENGTH:
            raise ValueError(f"Логин не может превышать {LOGIN_MAX_LENGTH} символов")
        return v

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date(cls, v: date) -> date:
        today = date.today()
        if v > today:
            raise ValueError("Дата рождения не может быть в будущем")
        # Сравнение по годам вместо дней, чтобы не вводить константу дней в году
        if v.year < today.year - USER_MAX_AGE_YEARS:
            raise ValueError("Некорректная дата рождения")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        return validate_password(v)

    @field_validator("phone")
    @classmethod
    def validate_phone_field(cls, v: str) -> str:
        return validate_phone(v)

    @field_validator("telegram")
    @classmethod
    def validate_telegram_field(cls, v: str) -> str:
        return validate_telegram(v)


class RegisterRequest(RegisterRequestBase):
    pass


class EmployeeRegisterRequest(RegisterRequestBase):
    """Регистрация сотрудника (AUTH-010): поля обычной регистрации + идентификатор.

    Идентификатор — часть проверки принадлежности к команде. Для MVP достаточно
    проверки формата (буква + 3 цифры + "room19"); сам идентификатор не хранится
    и не является секретом доступа.
    """

    identifier: str

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, v: str) -> str:
        v = _strip_required(v, "Идентификатор не может быть пустым")
        if not re.fullmatch(EMPLOYEE_IDENTIFIER_PATTERN, v):
            raise ValueError("Некорректный формат идентификатора")
        return v


class RegisterResponse(BaseModel):
    id: int
    full_name: str
    birth_date: date
    login: str
    phone: str
    telegram: str
    role: str


class MeResponse(BaseModel):
    id: int
    full_name: str
    role: str
      
      
class _CredentialsBase(BaseModel):
    """Общая валидация логина/пароля для всех эндпоинтов входа."""

    login: str
    password: str

    @field_validator("login")
    @classmethod
    def validate_login(cls, v: str) -> str:
        # Логин нормализуется так же, как при регистрации, чтобы оба парных
        # эндпоинта трактовали поле одинаково (без обрезки сработал бы неверный путь).
        return _strip_required(v, "Логин не может быть пустым")

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Сложность пароля при входе не проверяем: он уже провалидирован при
        # регистрации. Здесь — только отсутствие пустого значения.
        if not v:
            raise ValueError("Пароль не может быть пустым")
        return v


class LoginRequest(_CredentialsBase):
    pass


class EmployeeLoginRequest(_CredentialsBase):
    code: str

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _strip_required(v, "Код не может быть пустым")


class PasswordResetRequest(BaseModel):
    identifier: str

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, v: str) -> str:
        return _strip_required(v, "Логин или телефон не может быть пустым")


class PasswordResetConfirmRequest(PasswordResetRequest):
    code: str
    password: str

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _strip_required(v, "Код не может быть пустым")

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v: str) -> str:
        return validate_password(v)


class LoginResponse(BaseModel):
    id: int
    full_name: str
    birth_date: date
    login: str
    phone: str
    telegram: str
    role: str
