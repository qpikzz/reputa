from datetime import datetime

from app.schemas.telegram import ParsedTelegramChannel, TelegramMessage
from app.scoring.telegram_llm import (
    _evidence_from_llm,
    _fuzzy_int_value,
    _parse_llm_json,
    analyze_channel_semantics,
    build_gigachat_client,
    score_telegram_with_llm,
)
from app.scoring.telegram_scoring import score_telegram

# TG-002 (LLM): юнит-тесты не используют сеть и GigaChat API (RULES.md).
# Модель и авторизация подменяются фейковым клиентом / пустым ключом —
# проверяется сам разбор ответа и откат на словарные эвристики.


def _msg(text, date=None):
    return TelegramMessage(date=date, text=text)


def _channel(messages):
    return ParsedTelegramChannel(username="ch", messages=messages)


class _FakeClient:
    def __init__(self, response_text):
        self.chat = _FakeChat(response_text)

    def close(self):
        pass


class _FakeChat:
    def __init__(self, response_text):
        self._response_text = response_text

    def create(self, payload=None):
        from unittest.mock import MagicMock

        content = MagicMock(text=self._response_text)
        message = MagicMock(content=[content])
        response = MagicMock(messages=[message])
        return response


class _RaisingClient:
    class _Chat:
        def create(self, payload=None):
            raise RuntimeError("gigachat down")

    chat = _Chat()


VALID_JSON = """{"work_mentions": 0, "finance_mentions": 2, "positive_mentions": 1,
"debt_mentions": 0, "gambling_mentions": 1, "transfers": [
{"date": "2026-09-06", "amount": "30000", "counterparty": "Иван", "direction": "transfer"},
{"date": "не указано", "amount": "-12000", "counterparty": "Казино", "direction": "expense"}]}"""


class TestFuzzyIntValue:
    def test_exact_key(self):
        assert _fuzzy_int_value({"work_mentions": 3}, "work_mentions") == 3

    def test_typo_key_matches(self):
        # GigaChat опечатался: «finance_ments» вместо «finance_mentions».
        assert _fuzzy_int_value({"finance_ments": 2}, "finance_mentions") == 2

    def test_missing_key_returns_none(self):
        assert _fuzzy_int_value({"debt_mentions": 1}, "gambling_mentions") is None

    def test_non_int_returns_none(self):
        assert _fuzzy_int_value({"work_mentions": "2"}, "work_mentions") is None


class TestParseLlmJson:
    def test_plain_json(self):
        assert _parse_llm_json('{"a": 1}') == {"a": 1}

    def test_json_in_code_fence(self):
        text = "```json\n{\"ok\": true}\n```"
        assert _parse_llm_json(text) == {"ok": True}

    def test_trailing_garbage(self):
        assert _parse_llm_json('{"ok": true} ещё текст') == {"ok": True}

    def test_not_json_returns_none(self):
        assert _parse_llm_json("извините, не смог") is None

    def test_empty_returns_none(self):
        assert _parse_llm_json("") is None


class TestEvidenceFromLlm:
    def test_valid(self):
        ev = _evidence_from_llm(
            {
                "work_mentions": 2,
                "finance_mentions": 1,
                "positive_mentions": 0,
                "debt_mentions": 1,
                "gambling_mentions": 0,
                "transfers": [{"amount": "5000", "direction": "income"}],
            }
        )
        assert ev is not None
        assert ev["work_mentions"] == 2
        assert ev["debt_mentions"] == 1

    def test_missing_required_field_returns_none(self):
        assert _evidence_from_llm({"work_mentions": 1}) is None

    def test_transfers_not_list_returns_none(self):
        assert _evidence_from_llm(
            {
                "work_mentions": 1,
                "finance_mentions": 1,
                "positive_mentions": 1,
                "debt_mentions": 1,
                "gambling_mentions": 1,
                "transfers": {"amount": "5"},
            }
        ) is None

    def test_empty_transfers_ok(self):
        ev = _evidence_from_llm(
            {
                "work_mentions": 0,
                "finance_mentions": 0,
                "positive_mentions": 0,
                "debt_mentions": 0,
                "gambling_mentions": 0,
                "transfers": [],
            }
        )
        assert ev is not None and ev["transfers"] == []


class TestScoreTelegramWithLlm:
    def _channel_with_dates(self):
        return _channel(
            [
                _msg("Перевод 30000", datetime(2026, 1, 1)),
                _msg("Выиграл в казино", datetime(2026, 1, 5)),
            ]
        )

    def test_llm_analysis_applied(self):
        channel = self._channel_with_dates()
        result = score_telegram_with_llm(channel, client=_FakeClient(VALID_JSON))
        assert result["score_contribution"] == 50  # 50 +10(фин) +10(поступления) -20(азарт)
        assert any("азарт" in r for r in result["risk_factors"])
        assert any("денежные поступления" in s for s in result["positive_signals"])
        assert "Распознанные переводы" in result["report_content"]
        assert "расходы:" in result["report_content"]
        assert "-12000" in result["report_content"]

    def test_expense_not_counted_as_income(self):
        channel = self._channel_with_dates()
        only_expense = VALID_JSON.replace('"30000"', "0").replace(
            '"direction": "transfer"', '"direction": "expense"'
        )
        result = score_telegram_with_llm(channel, client=_FakeClient(VALID_JSON))
        result2 = score_telegram_with_llm(channel, client=_FakeClient(only_expense))
        # У второго канала все переводы — расход, сигнал поступлений не сработал.
        assert any("денежные поступления" in s for s in result["positive_signals"])
        assert not any("денежные поступления" in s for s in result2["positive_signals"])

    def test_falls_back_on_non_json(self):
        channel = self._channel_with_dates()
        assert score_telegram_with_llm(
            channel, client=_FakeClient("  ") ) == score_telegram(channel)

    def test_falls_back_on_api_error(self):
        channel = self._channel_with_dates()
        assert score_telegram_with_llm(
            channel, client=_RaisingClient()) == score_telegram(channel)

    def test_falls_back_without_credentials(self, monkeypatch):
        from app.scoring import telegram_llm

        monkeypatch.setattr(telegram_llm.settings, "GIGACHAT_CREDENTIALS", "")
        channel = self._channel_with_dates()
        assert score_telegram_with_llm(channel) == score_telegram(channel)

    def test_empty_channel_neutral(self):
        result = score_telegram_with_llm(_channel([]), client=_FakeClient(VALID_JSON))
        assert result["score_contribution"] == 50
        assert result["positive_signals"] == []
        assert result["risk_factors"] == []


class TestBuildGigachatClient:
    def test_none_without_credentials(self, monkeypatch):
        from app.scoring import telegram_llm

        monkeypatch.setattr(telegram_llm.settings, "GIGACHAT_CREDENTIALS", "")
        assert build_gigachat_client() is None


class TestAnalyzeChannelSemantics:
    def test_none_without_credentials(self, monkeypatch):
        from app.scoring import telegram_llm

        monkeypatch.setattr(telegram_llm.settings, "GIGACHAT_CREDENTIALS", "")
        assert analyze_channel_semantics(_channel([_msg("hi")])) is None

    def test_returns_typed_analysis(self):
        channel = _channel(
            [_msg("Перевод 30000", datetime(2026, 1, 1))]
        )
        analysis = analyze_channel_semantics(channel, client=_FakeClient(VALID_JSON))
        assert analysis is not None
        assert analysis["gambling_mentions"] == 1
        assert len(analysis["transfers"]) == 2