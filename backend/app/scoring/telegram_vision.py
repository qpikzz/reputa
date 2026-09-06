from io import BytesIO
from typing import Callable
import urllib.error
import urllib.request

from google import genai
from google.genai import types

from app.core.config import settings
from app.schemas.telegram import ParsedTelegramChannel, TelegramMessage

# TG-002 (OCR): распознавание изображений в постах Telegram-канала через
# Gemini 2.5 Flash. Анализ канала работает по тексту постов; текст из фото
# (переводы, чеки, скрины банковских операций) добавляется к корпусу отдельно.
#
# Дизайн: всё «красиво деградирует» — без API-ключа, при сетевой ошибке или
# ошибке Gemini канал возвращается без изменений, скоринг не ломается
# (аналогично TG-001, где недоступный канал просто не учитывается в оценке).

GEMINI_MODEL = "gemini-3.6-flash"

IMAGE_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 МБ — защита от слишком тяжёлых картинок
IMAGE_DOWNLOAD_TIMEOUT = 10  # секунд на скачивание одного фото
GEMINI_REQUEST_TIMEOUT = 20  # секунд на распознавание одного изображения

OCR_PROMPT = (
    "Ты — ассистент сервиса кредитного скоринга. Извлеки из изображения текст "
    "и его суть. Если на картинке платёж, перевод, чек, зачисление, остаток или "
    "скан документа — укажи сумму, дату, тип операции и контрагента. "
    "Отвечай кратко, по-русски. Если распознать нечего — напиши «фото без текста»."
)


def _download_image(url: str) -> bytes | None:
    """Скачивает изображение. Возвращает None при сетевой/размерной ошибке."""
    try:
        with urllib.request.urlopen(url, timeout=IMAGE_DOWNLOAD_TIMEOUT) as resp:
            content = resp.read(IMAGE_MAX_SIZE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if len(content) > IMAGE_MAX_SIZE_BYTES:
        return None
    return content


def _ocr_image_through_gemini(client: genai.Client, image_bytes: bytes) -> str | None:
    """Распознаёт одно изображение через Gemini. None при ошибке API."""
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part(text=OCR_PROMPT),
                types.Part(
                    inline_data=types.Blob(
                        data=image_bytes,
                        mime_type="image/jpeg",
                    )
                ),
            ],
        )
        text = (response.text or "").strip()
        if not text or text == "фото без текста":
            return None
        return text
    except Exception:
        # Любая ошибка Gemini (квота, сеть, формат) не должна ломать скоринг.
        return None


def build_gemini_ocr_text(
    client: genai.Client | None = None,
) -> Callable[[bytes], str | None]:
    """Собирает функцию «байты изображения → текст» на базе Gemini.

    Без API-ключа возвращает функцию, которая всегда даёт None —
    OCR-обогащение просто не работает.
    """
    if not settings.GEMINI_API_KEY:
        return lambda _image_bytes: None
    if client is None:
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
        except Exception:
            return lambda _image_bytes: None
    return lambda image_bytes: _ocr_image_through_gemini(client, image_bytes)


def enrich_channel_with_ocr(
    channel: ParsedTelegramChannel,
    ocr_text: Callable[[bytes], str | None] | None = None,
) -> ParsedTelegramChannel:
    """Возвращает копию канала, где к тексту постов добавлен распознанный текст фото.

    `ocr_text` — функция `bytes → str | None`; по умолчанию — Gemini (см. выше).
    Фото без результата распознавания не меняют текст поста. Канал изолирован:
    исходные объекты не мутируются.
    """
    if ocr_text is None:
        ocr_text = build_gemini_ocr_text()

    enriched: list[TelegramMessage] = []
    for message in channel.messages:
        recognized: list[str] = []
        for url in message.photo_urls:
            image_bytes = _download_image(url)
            if image_bytes is None:
                continue
            text = ocr_text(image_bytes)
            if text:
                recognized.append(text)
        text = message.text
        if recognized:
            text = text + "\n\n[OCR: " + " | ".join(recognized) + "]"
        enriched.append(
            TelegramMessage(
                date=message.date,
                text=text,
                photo_urls=list(message.photo_urls),
            )
        )
    return ParsedTelegramChannel(username=channel.username, messages=enriched)