import html
import re
import urllib.error
import urllib.request
from datetime import datetime

from app.schemas.telegram import ParsedTelegramChannel, TelegramMessage

# TG-001: парсинг публичного Telegram-канала.
#
# Сообщения произвольного публичного канала читаются через публичную
# web-preview-страницу https://t.me/s/<username> — единственный способ получить
# историю канала без членства в нём. Telegram Bot API (getChat/getUpdates)
# отдаёт сообщения только каналов, в которые бот добавлен, поэтому для MVP
# (любой публичный канал из заявки) он не подходит.
#
# Если канал недоступен (приватный/удалённый, сетевая ошибка, невалидный
# username) — возвращаем None. TG-002/TG-003 трактуют это как «telegram-сигнала
# нет» и используют только оценку по выписке (см. PLAN.md, «Откат»).

TELEGRAM_CHANNEL_PREVIEW_URL = "https://t.me/s/{username}"
TELEGRAM_CHANNEL_URL_TIMEOUT = 10

# Telegram-username: 5–32 символа [a-zA-Z0-9_], не бывает только из цифр.
_TELEGRAM_USERNAME_RE = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9_]{5,}$")

# Ссылки вида t.me/<user>, t.me/s/<user>, telegram.me/<user>, http(s)://...
_TELEGRAM_URL_RE = re.compile(r"(?:t\.me/|telegram\.me/)(?:s/)?([A-Za-z0-9_]+)")

# Начало одного поста на web-preview-странице. Посты — соседние siblings, поэтому
# блок каждого поста — срез страницы между двумя такими открывающими тегами.
_WRAP_OPEN_RE = re.compile(r'<div class="tgme_widget_message_wrap[^>]*>')

# Текст поста. Внутри могут быть только <a ...> и <br>, вложенных <div> нет.
_TEXT_DIV_RE = re.compile(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', re.S)
_TIME_RE = re.compile(r'<time datetime="([^"]+)"')

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n\s*\n+")

# TG-002 (OCR): ссылки на фото лежат в CSS background-image фотоблоков
# <a class="tgme_widget_message_photo_wrap ..." style="...;background-image:url('...')">.
# На web-preview это cdn4.telesco.pe (или относительные url), т.к. <img> в постах нет.
_PHOTO_BG_URL_RE = re.compile(
    r'tgme_widget_message_photo_wrap[^>]*background-image:\s*url\([\'"]?([^\'")]+)[\'"]?\)',
    re.S,
)


def parse_channel_username(channel: str) -> str | None:
    """Достаёт username канала из @user, t.me/... или голого имени.

    Nothing для нераспознаваемого адреса: приватный invite-link (t.me/+xxx),
    не-ASCII строка, слишком короткое имя.
    """
    value = channel.strip()
    if not value or not value.isascii():
        return None

    value = value.replace("@", "")
    url_match = _TELEGRAM_URL_RE.search(value)
    if url_match:
        return url_match.group(1)
    if _TELEGRAM_USERNAME_RE.fullmatch(value):
        return value
    return None


def _extract_message_text(block: str) -> str:
    match = _TEXT_DIV_RE.search(block)
    if not match:
        return ""
    content = match.group(1)
    content = _BR_RE.sub("\n", content)
    content = _TAG_RE.sub("", content)
    content = html.unescape(content)
    content = _MULTI_SPACE_RE.sub(" ", content)
    content = _MULTI_NEWLINE_RE.sub("\n", content)
    return content.strip()


def _extract_message_date(block: str) -> datetime | None:
    match = _TIME_RE.search(block)
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1))
    except ValueError:
        return None


def _extract_message_photos(block: str) -> list[str]:
    """Достаёт прямые ссылки на фото поста.

    Фото на web-preview заданы не `<img>`, а CSS-фоном
    `background-image:url(...)` в `tgme_widget_message_photo_wrap`.
    """
    urls: list[str] = []
    for match in _PHOTO_BG_URL_RE.finditer(block):
        url = match.group(1).strip()
        if url.startswith("//"):
            url = "https:" + url
        urls.append(url)
    return urls


def parse_channel_page(body: str, username: str) -> ParsedTelegramChannel:
    """Разбирает HTML web-preview-страницы t.me/s/<user> в список сообщений.

    Включаются посты с текстом и посты-фото без подписи (TG-002: их содержимое
    распознаётся OCR-модулем). Пустые медиа-посты без текста и фото пропускаются.
    """
    starts = [m.start() for m in _WRAP_OPEN_RE.finditer(body)]
    messages: list[TelegramMessage] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(body)
        block = body[start:end]
        text = _extract_message_text(block)
        photo_urls = _extract_message_photos(block)
        if not text and not photo_urls:
            continue
        messages.append(
            TelegramMessage(
                date=_extract_message_date(block),
                text=text,
                photo_urls=photo_urls,
            )
        )
    return ParsedTelegramChannel(username=username, messages=messages)


def fetch_channel_messages(channel: str) -> ParsedTelegramChannel | None:
    """Скачивает и разбирает публичный канал.

    Возвращает None, если username не распознан или канал недоступен
    (приватный/удалённый/сетевая ошибка) — такие случаи не должны ломать
    основной сценарий.
    """
    username = parse_channel_username(channel)
    if username is None:
        return None

    url = TELEGRAM_CHANNEL_PREVIEW_URL.format(username=username)
    try:
        with urllib.request.urlopen(url, timeout=TELEGRAM_CHANNEL_URL_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None

    return parse_channel_page(body, username)