from pydantic_settings import BaseSettings

from app.core.constants import COOKIE_NAME


class Settings(BaseSettings):
    PROJECT_NAME: str = "Reputa"
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/reputa"
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 часа
    # Единый источник имени cookie — constants.COOKIE_NAME (AUTH-007).
    # Его же читают get_current_user и middleware, поэтому set/read не разойдутся.
    ACCESS_TOKEN_COOKIE_NAME: str = COOKIE_NAME
    COOKIE_SECURE: bool = False  # включать True только за HTTPS
    # Gemini API (TG-002 OCR): ключ из Google AI Studio. Пустой — OCR-обогащение
    # канала выключено, анализ работает только по тексту постов.
    GEMINI_API_KEY: str = ""
    # GigaChat API (TG-002, анализ текста канала). Пустой credentials —
    # LLM-анализ выключен, работает fallback на словарные эвристики.
    GIGACHAT_CREDENTIALS: str = ""
    GIGACHAT_MODEL: str = "GigaChat-2"
    GIGACHAT_SCOPE: str = "GIGACHAT_API_PERS"
    GIGACHAT_BASE_URL: str = "https://api.giga.chat/v1"
    # Официальные примеры GigaChat SDK идут с verify_ssl_certs=False: без
    # установки корневого сертификата НУЦ Минцифры проверка TLS падает.
    # Включить True после установки сертификата (RULES.md, безопасность).
    GIGACHAT_VERIFY_SSL_CERTS: bool = False

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
