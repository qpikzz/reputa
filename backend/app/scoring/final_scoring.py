from app.scoring.stmt_scoring import StatementScoringResult
from app.scoring.telegram_scoring import TelegramScoringResult


# TG-003: объединение оценки по банковской выписке (STMT-002) и
# Telegram-канала (TG-002) в единый итоговый балл.
#
# Формула (если есть оба сигнала):
#   final_score = stmt_score * 0.7 + tg_score_contribution * 0.3
#
# Если Telegram-сигнал отсутствует (канал не указан, недоступен или
# недостаточно данных) — используется только оценка по выписке (100%).

# Метрики портрета (0–10) и текстовый отчёт складываются / усредняются
# из обоих источников при наличии Telegram-данных.

_WEIGHT_STMT = 0.7
_WEIGHT_TG = 0.3


def calculate_final_profile(
    stmt_result: StatementScoringResult,
    tg_result: TelegramScoringResult | None = None,
) -> dict:
    """Объединяет оценку по выписке и Telegram-сигнал в итоговый профиль.

    Если tg_result не передан или равен None — возвращает результат
    исключительно по выписке (100% вес stmt_result). При наличии
    Telegram-сигнала используется формула 70/30.
    """
    if not tg_result:
        return {
            "score": stmt_result["score"],
            "positive_signals": stmt_result["positive_signals"],
            "risk_factors": stmt_result["risk_factors"],
            "stability_score": stmt_result["stability_score"],
            "financial_literacy_score": stmt_result["financial_literacy_score"],
            "responsibility_score": stmt_result["responsibility_score"],
            "report_content": stmt_result["report_content"],
        }

    stmt_score = stmt_result["score"]
    tg_score = tg_result["score_contribution"]

    final_score = int(
        round(stmt_score * _WEIGHT_STMT + tg_score * _WEIGHT_TG)
    )
    final_score = max(0, min(100, final_score))

    positive_signals = stmt_result["positive_signals"] + tg_result["positive_signals"]
    risk_factors = stmt_result["risk_factors"] + tg_result["risk_factors"]

    def _avg(a: int, b: int) -> int:
        return max(0, min(10, round((a + b) / 2.0)))

    stability = _avg(stmt_result["stability_score"], tg_result["stability_score"])
    fin_lit = _avg(
        stmt_result["financial_literacy_score"],
        tg_result["financial_literacy_score"],
    )
    resp = _avg(stmt_result["responsibility_score"], tg_result["responsibility_score"])

    report_content = f"{stmt_result['report_content']}\n\n{tg_result['report_content']}"

    return {
        "score": final_score,
        "positive_signals": positive_signals,
        "risk_factors": risk_factors,
        "stability_score": stability,
        "financial_literacy_score": fin_lit,
        "responsibility_score": resp,
        "report_content": report_content,
    }
