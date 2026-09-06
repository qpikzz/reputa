from unittest.mock import MagicMock

from app.schemas.telegram import ParsedTelegramChannel, TelegramMessage
from app.scoring.telegram_vision import (
    build_gemini_ocr_text,
    enrich_channel_with_ocr,
)

# TG-002 (OCR): тесты с фейковой OCR-функцией и моком скачивания — реальные
# вызовы Gemini и сеть в unit-тестах не используются (RULES.md).


def _channel(messages):
    return ParsedTelegramChannel(username="ch", messages=messages)


def _msg(text="", photo_urls=None):
    return TelegramMessage(date=None, text=text, photo_urls=photo_urls or [])


class TestEnrichChannelWithOcr:
    def test_appends_recognized_text_to_message(self, monkeypatch):
        raw = _msg("Пост", photo_urls=["https://cdn4.telesco.pe/file/a.jpg"])
        channel = _channel([raw])
        monkeypatch.setattr(
            "app.scoring.telegram_vision._download_image",
            lambda url: b"image-bytes",
        )
        result = enrich_channel_with_ocr(channel, ocr_text=lambda b: "Перевод 5000 руб.")
        assert result.username == "ch"
        assert "[OCR: Перевод 5000 руб.]" in result.messages[0].text
        # исходный объект не мутирован
        assert raw.text == "Пост"
        assert raw.photo_urls == ["https://cdn4.telesco.pe/file/a.jpg"]

    def test_multiple_photos_joined(self, monkeypatch):
        channel = _channel(
            [
                _msg(
                    text="П",
                    photo_urls=[
                        "https://cdn4.telesco.pe/file/a.jpg",
                        "https://cdn4.telesco.pe/file/b.jpg",
                    ],
                )
            ]
        )
        monkeypatch.setattr("app.scoring.telegram_vision._download_image", lambda url: b"img")
        result = enrich_channel_with_ocr(
            channel,
            ocr_text=lambda b: "Чек 1200",
        )
        assert result.messages[0].text.count("[OCR") == 1
        assert "Чек 1200" in result.messages[0].text

    def test_download_failure_leaves_text_unchanged(self, monkeypatch):
        channel = _channel([_msg("Текст", photo_urls=["https://cdn4.telesco.pe/file/a.jpg"])])
        monkeypatch.setattr("app.scoring.telegram_vision._download_image", lambda url: None)
        result = enrich_channel_with_ocr(channel, ocr_text=lambda b: "Текст из фото")
        assert result.messages[0].text == "Текст"

    def test_ocr_none_leaves_text_unchanged(self, monkeypatch):
        channel = _channel([_msg("Текст", photo_urls=["https://cdn4.telesco.pe/file/a.jpg"])])
        monkeypatch.setattr("app.scoring.telegram_vision._download_image", lambda url: b"img")
        result = enrich_channel_with_ocr(channel, ocr_text=lambda b: None)
        assert result.messages[0].text == "Текст"

    def test_no_photos_channel_unchanged(self, monkeypatch):
        channel = _channel([_msg("Просто текст")])
        monkeypatch.setattr("app.scoring.telegram_vision._download_image", lambda url: b"img")
        result = enrich_channel_with_ocr(channel, ocr_text=lambda b: "скип")
        assert result.messages[0].text == "Просто текст"

    def test_download_oversize_returns_none(self, monkeypatch):
        from app.scoring import telegram_vision

        resp = MagicMock()
        resp.read.return_value = b"x" * (telegram_vision.IMAGE_MAX_SIZE_BYTES + 1)
        resp.__enter__.return_value = resp
        monkeypatch.setattr("urllib.request.urlopen", MagicMock(return_value=resp))
        assert telegram_vision._download_image("https://cdn4.telesco.pe/file/a.jpg") is None


class TestBuildGeminiOcrText:
    def test_returns_none_always_without_api_key(self, monkeypatch):
        from app.scoring import telegram_vision

        monkeypatch.setattr(telegram_vision.settings, "GEMINI_API_KEY", "")
        ocr = build_gemini_ocr_text()
        assert ocr(b"whatever") is None