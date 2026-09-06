from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.scoring.telegram_channel import (
    fetch_channel_messages,
    parse_channel_page,
    parse_channel_username,
)
from app.schemas.telegram import ParsedTelegramChannel

# Снимок структуры публичной web-preview-страницы t.me/s/<user>: два поста,
# первый — с <a> и <br> внутри текста и с временем, второй — без времени.
SAMPLE_PAGE = (
    "<!DOCTYPE html>"
    '<html><head><title>Channel</title></head><body>'
    '<h3 class="tgme_page_title">Channel</h3>'
    '<div class="tgme_page_action">Подписаться</div>'
    '<div class="tgme_widget_message_wrap js-widget_message_wrap" data-post="channel/10">'
    '<div class="tgme_widget_message">'
    '<div class="tgme_widget_message_bubble">'
    '<div class="tgme_widget_message_text js-message_text" dir="auto">'
    "Привет, Мир! <a href=\"https://t.me/hashtag/test\">#test</a>"
    "<br>новая строка &amp; амперсанд"
    "</div>"
    '<div class="tgme_widget_message_footer">'
    '<span class="tgme_widget_message_views">107</span>'
    '<a class="tgme_widget_message_date" href="https://t.me/channel/10">'
    '<time datetime="2026-01-05T12:34:56+00:00">08:34</time>'
    "</a>"
    "</div>"
    "</div></div></div>"
    '<div class="tgme_widget_message_wrap" data-post="channel/11">'
    '<div class="tgme_widget_message">'
    '<div class="tgme_widget_message_bubble">'
    '<div class="tgme_widget_message_text js-message_text" dir="auto">'
    "Второе сообщение без времени"
    "</div>"
    "</div></div></div>"
    "</body></html>"
)


class TestParseChannelUsername:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("channel", "channel"),
            ("@channel", "channel"),
            ("https://t.me/channel", "channel"),
            ("https://t.me/s/channel", "channel"),
            ("t.me/s/channel", "channel"),
            ("telegram.me/my_channel", "my_channel"),
            ("https://telegram.me/s/my_channel", "my_channel"),
            ("  @channel  ", "channel"),
        ],
    )
    def test_valid_usernames(self, value, expected):
        assert parse_channel_username(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "abc",  # короче 5 символов
            "12345",  # только цифры
            "t.me/+private_invite",  # приватный invite-link
            "@",  # один @ без имени
            "канал",  # не-ASCII
        ],
    )
    def test_invalid_usernames(self, value):
        assert parse_channel_username(value) is None

    def test_post_link_is_trimmed_to_channel_name(self):
        # Ссылка на конкретный пост содержит username до первого разделителя.
        assert parse_channel_username("https://t.me/foo_bar/123") == "foo_bar"


class TestParseChannelPage:
    def test_parses_text_and_day_ordered(self):
        result = parse_channel_page(SAMPLE_PAGE, "channel")
        assert isinstance(result, ParsedTelegramChannel)
        assert result.username == "channel"

        assert len(result.messages) == 2
        first, second = result.messages
        assert first.text == "Привет, Мир! #test\nновая строка & амперсанд"
        assert first.date == datetime.fromisoformat("2026-01-05T12:34:56+00:00")
        assert second.text == "Второе сообщение без времени"
        assert second.date is None

    def test_messages_without_text_but_with_photo_are_kept(self):
        # TG-002: посты-фото без подписи не выбрасываются — их распознаёт OCR.
        page = (
            '<div class="tgme_widget_message_wrap js-widget_message_wrap" data-post="ch/1">'
            '<div class="tgme_widget_message"><a class="tgme_widget_message_photo_wrap" '
            "style=\"background-image:url('https://cdn4.telesco.pe/file/pic.jpg')\"></a>"
            "</div></div>"
            '<div class="tgme_widget_message_wrap js-widget_message_wrap" data-post="ch/2">'
            '<div class="tgme_widget_message_text js-message_text" dir="auto">Текст</div>'
            "</div>"
        )
        result = parse_channel_page(page, "ch")
        assert len(result.messages) == 2
        assert result.messages[0].text == ""
        assert result.messages[0].photo_urls == ["https://cdn4.telesco.pe/file/pic.jpg"]
        assert result.messages[1].text == "Текст"

    def test_messages_without_text_and_photo_are_skipped(self):
        # Пустой медиа-пост без текста и без фото (стример и т.п.) — пропускается.
        page = (
            '<div class="tgme_widget_message_wrap js-widget_message_wrap" data-post="ch/1">'
            '<div class="tgme_widget_message"><a class="tgme_widget_message_photo_wrap" href="#"></a>'
            "</div></div>"
            '<div class="tgme_widget_message_wrap js-widget_message_wrap" data-post="ch/2">'
            '<div class="tgme_widget_message_text js-message_text" dir="auto">Текст</div>'
            "</div>"
        )
        result = parse_channel_page(page, "ch")
        assert len(result.messages) == 1
        assert result.messages[0].text == "Текст"

    def test_empty_page_gives_empty_messages(self):
        result = parse_channel_page("<html><body></body></html>", "channel")
        assert isinstance(result, ParsedTelegramChannel)
        assert result.messages == []

    def test_photo_urls_extracted_from_bg_image(self):
        # TG-002 (OCR): ссылки на фото — CSS background-image фото-обёртки.
        page = (
            '<div class="tgme_widget_message_wrap js-widget_message_wrap" data-post="ch/1">'
            '<div class="tgme_widget_message">'
            '<a class="tgme_widget_message_photo_wrap" href="https://t.me/ch/1" '
            "style=\"width:800px;background-image:url('https://cdn4.telesco.pe/file/abc.jpg')\">"
            '<div class="tgme_widget_message_photo"></div>'
            "</a>"
            '<div class="tgme_widget_message_text js-message_text" dir="auto">Пост с фото</div>'
            "</div></div>"
        )
        result = parse_channel_page(page, "ch")
        assert len(result.messages) == 1
        assert result.messages[0].photo_urls == ["https://cdn4.telesco.pe/file/abc.jpg"]

    def test_photo_urls_scheme_relative_become_https(self):
        page = (
            '<div class="tgme_widget_message_wrap" data-post="ch/1">'
            '<a class="tgme_widget_message_photo_wrap" '
            "style=\"background-image:url('//cdn4.telesco.pe/file/x.jpg')\"></a>"
            '<div class="tgme_widget_message_text js-message_text">текст</div>'
            "</div>"
        )
        result = parse_channel_page(page, "ch")
        assert result.messages[0].photo_urls == ["https://cdn4.telesco.pe/file/x.jpg"]

    def test_photo_urls_empty_when_no_photo(self):
        result = parse_channel_page(SAMPLE_PAGE, "channel")
        assert all(msg.photo_urls == [] for msg in result.messages)


class TestFetchChannelMessages:
    def test_fetch_parses_remote_page(self):
        with patch("urllib.request.urlopen") as urlopen:
            resp = MagicMock()
            resp.read.return_value = SAMPLE_PAGE.encode("utf-8")
            resp.__enter__.return_value = resp
            urlopen.return_value = resp

            result = fetch_channel_messages("https://t.me/s/channel")

        urlopen.assert_called_once()
        call_url = urlopen.call_args.args[0]
        assert call_url == "https://t.me/s/channel"
        assert result is not None
        assert result.username == "channel"
        assert len(result.messages) == 2

    def test_fetch_network_error_returns_none(self):
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
            assert fetch_channel_messages("@channel") is None

    def test_fetch_invalid_username_returns_none_without_network(self):
        with patch("urllib.request.urlopen") as urlopen:
            assert fetch_channel_messages("12345") is None
        urlopen.assert_not_called()

    def test_fetch_private_invite_link_returns_none_without_network(self):
        with patch("urllib.request.urlopen") as urlopen:
            assert fetch_channel_messages("https://t.me/+AbC123") is None
        urlopen.assert_not_called()