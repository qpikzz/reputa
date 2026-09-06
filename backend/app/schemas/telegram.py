from datetime import datetime

from pydantic import BaseModel, Field


class TelegramMessage(BaseModel):
    date: datetime | None = None
    text: str
    # TG-002 (OCR): прямые ссылки на фото из поста. Изображения распознаются
    # отдельно (Gemini), т.к. текст и фото в анализе лексики не смешиваются.
    photo_urls: list[str] = Field(default_factory=list)


class ParsedTelegramChannel(BaseModel):
    username: str
    messages: list[TelegramMessage] = Field(default_factory=list)