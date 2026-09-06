from datetime import datetime, timedelta, timezone

import pytest

from app.scoring.telegram_scoring import (
    _count_hits,
    _post_regularity_score,
    score_telegram,
)
from app.schemas.telegram import ParsedTelegramChannel, TelegramMessage


def _channel(
    texts: list[str],
    start: datetime | None = None,
    step_days: int = 1,
    username: str = "test_channel",
) -> ParsedTelegramChannel:
    """Собирает канал из текстов сообщений с регулярными датами.

    Если start задан, сообщениям проставляются даты: start, start+step_days, ...
    """
    messages = []
    for i, text in enumerate(texts):
        date = start + timedelta(days=i * step_days) if start else None
        messages.append(TelegramMessage(date=date, text=text))
    return ParsedTelegramChannel(username=username, messages=messages)


class TestEmptyChannel:
    def test_no_messages(self):
        result = score_telegram(ParsedTelegramChannel(username="empty", messages=[]))
        assert result["score_contribution"] == 50
        assert result["positive_signals"] == []
        assert result["risk_factors"] == []
        assert result["stability_score"] == 5
        assert result["financial_literacy_score"] == 5
        assert result["responsibility_score"] == 5
        assert "Недостаточно текстовых данных" in result["report_content"]

    def test_messages_without_text(self):
        result = score_telegram(
            ParsedTelegramChannel(
                username="empty",
                messages=[TelegramMessage(text="   "), TelegramMessage(text="")],
            )
        )
        assert result["score_contribution"] == 50
        assert result["stability_score"] == 5


class TestLexicalSignals:
    def test_work_channel(self):
        result = score_telegram(
            _channel(["моя работа связана с проектом, новый заказ для клиента"])
        )
        assert any(
            "Упоминания трудовой деятельности" in signal
            for signal in result["positive_signals"]
        )
        assert result["score_contribution"] > 50

    def test_financial_channel(self):
        result = score_telegram(
            _channel(["инвестиции, бюджет, накопления и дивиденды — моя тема"])
        )
        assert "Финансовая осведомлённость" in result["positive_signals"][0]
        assert result["financial_literacy_score"] >= 7

    def test_financial_signal_via_ocr_mentions(self):
        # OCR-текст фото (переводы/чеки) участвует в анализе лексики наравне с текстом постов.
        result = score_telegram(
            _channel(["Экран перевода: Перевод 5000 руб. Пополнение счета"])
        )
        assert any(
            "Финансовая осведомлённость" in signal
            for signal in result["positive_signals"]
        )

    def test_money_transfer_signal_with_amount(self):
        # «Перевод + сумма» в сообщении — признак поступления денег даже при одной упоминании.
        result = score_telegram(_channel(["Перевод30.000"]))
        assert any(
            "Подтверждённые денежные поступления" in signal
            for signal in result["positive_signals"]
        )
        assert result["score_contribution"] > 50

    def test_money_transfer_signal_with_spaces(self):
        result = score_telegram(_channel(["Зачисление на карту 5 000,50 руб"]))
        assert any(
            "Подтверждённые денежные поступления" in signal
            for signal in result["positive_signals"]
        )

    def test_money_verb_without_amount_not_a_signal(self):
        # «перевод» без суммы — не считается поступлением (защита от ложных срабатываний).
        result = score_telegram(_channel(["перевод на новую работу"]))
        assert not any(
            "Подтверждённые денежные поступления" in signal
            for signal in result["positive_signals"]
        )

    def test_amount_without_money_verb_not_a_signal(self):
        result = score_telegram(_channel(["подписался 5000 человек, рост канала"]))
        assert not any(
            "Подтверждённые денежные поступления" in signal
            for signal in result["positive_signals"]
        )

    def test_positive_channel(self):
        result = score_telegram(
            _channel(["отлично, всё получилось, спасибо за помощь, классный день"])
        )
        assert any(
            "Позитивный характер публикаций" in signal
            for signal in result["positive_signals"]
        )

    def test_debt_risk_channel(self):
        result = score_telegram(
            _channel(["кредит и долг сильно давили на меня весь год"])
        )
        assert any(
            "Упоминание кредитных обязательств" in factor
            for factor in result["risk_factors"]
        )
        assert result["score_contribution"] < 50

    def test_gambling_risk_channel(self):
        result = score_telegram(
            _channel(["казино, ставки и слоты — мои любимые развлечения"])
        )
        assert any(
            "Признаки азартной активности" in factor
            for factor in result["risk_factors"]
        )
        assert result["score_contribution"] < 50

    def test_neutral_channel(self):
        result = score_telegram(
            _channel(["сегодня хорошая погода, день прошёл спокойно"])
        )
        assert result["positive_signals"] == []
        assert result["risk_factors"] == []
        assert result["score_contribution"] == 50


class TestPortraitMetrics:
    @pytest.mark.parametrize(
        "texts",
        [
            [],
            ["сегодня хорошая погода"],
            ["работа проект заказ работа"],
            ["казино ставки кредит долг"],
        ],
    )
    @pytest.mark.parametrize("start", [None, datetime(2026, 1, 1, tzinfo=timezone.utc)])
    def test_metrics_within_bounds(self, texts, start):
        result = score_telegram(_channel(texts, start=start))
        for metric in (
            "stability_score",
            "financial_literacy_score",
            "responsibility_score",
        ):
            assert 0 <= result[metric] <= 10, f"{metric} вне диапазона: {result[metric]}"

    def test_stability_grows_with_regular_posts(self):
        daily = _channel(
            ["работа работа"] * 10,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            step_days=1,
        )
        sparse = _channel(
            ["работа работа"] * 10,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            step_days=30,
        )
        assert (
            score_telegram(daily)["stability_score"]
            >= score_telegram(sparse)["stability_score"]
        )

    def test_single_message_has_low_stability(self):
        result = score_telegram(_channel(["работа работа"]))
        assert result["stability_score"] == 5


class TestReport:
    def test_report_mentions_channel_stats(self):
        channel = _channel(["работа и проект"], username="citynews")
        result = score_telegram(channel)
        assert "@citynews" in result["report_content"]
        assert "сообщений" in result["report_content"]

    def test_report_lists_risk_factors(self):
        result = score_telegram(_channel(["кредит задолженность коллектор"]))
        assert "Факторы риска" in result["report_content"]
        assert "Упоминание кредитных обязательств" in result["report_content"]

    def test_report_neutral_when_no_signals(self):
        result = score_telegram(_channel(["просто мысли вслух"]))
        assert "Выраженных позитивных сигналов или факторов риска не обнаружено" in result["report_content"]


class TestHelpers:
    def test_post_regularity_daily_is_one(self):
        channel = _channel(
            ["a", "b", "c"],
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            step_days=1,
        )
        assert _post_regularity_score(channel) == 1.0

    def test_post_regularity_single_message_is_zero(self):
        channel = _channel(["a"])
        assert _post_regularity_score(channel) == 0.0

    def test_post_regularity_sparse_is_low(self):
        channel = _channel(
            ["a", "b", "c"],
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            step_days=30,
        )
        assert _post_regularity_score(channel) < 0.5

    def test_count_hits_substring(self):
        assert _count_hits("работа и работа", {"работа"}) == 2
        assert _count_hits("кредит", {"кредит"}) == 1