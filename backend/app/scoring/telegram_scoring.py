from typing import TypedDict
import re

import numpy as np

from app.schemas.telegram import ParsedTelegramChannel

# TG-002: расчёт скоринга и психологического портрета по данным канала.
#
# На MVP — эвристики по лексике: ключевые слова + плотность упоминаний.
# TG-003 объединит этот сигнал с оценкой по выписке.


class TelegramScoringResult(TypedDict):
    score_contribution: int
    positive_signals: list[str]
    risk_factors: list[str]
    stability_score: int
    financial_literacy_score: int
    responsibility_score: int
    report_content: str


class TelegramScoringEvidence(TypedDict):
    """Доказательства по категориям, подставляемые в формулу скоринга.

    Формула (числа вклада, метрики портрета) единая; различается только
    источник доказательств: словарные эвристики (score_telegram) либо
    LLM-анализ GigaChat (telegram_llm.score_telegram_with_llm).
    """
    work_hits: int
    fin_hits: int
    pos_hits: int
    debt_hits: int
    gambling_hits: int
    has_money_transfer: bool
    # Краткое перечисление распознанных переводов для отчёта, например
    # "40 541,32 ₽ (зарплата), 4 490 ₽ (перевод)". Пустое — не влияет на отчёт.
    transfers_summary: str


# ---------- Лексические словари ----------

_WORDS_WORK = {
    "работа", "проект", "клиент", "заказ", "задача", "дедлайн",
    "фриланс", "заказы", "проекты", "клиенты", "задачи",
    "сотрудник", "коллега", "офис", "встреча", "совещание",
    "отчёт", "отчет", "документ", "смета", "договор",
}

_WORDS_FINANCE = {
    "инвестиции", "депозит", "бюджет", "накопления", "портфель",
    "дивиденды", "сбережения", "счёт", "счет", "прибыль",
    "доход", "акции", "облигации", "фонд", "процент",
    "ставка", "кэшбек", "кешбек", "финанс",
    # Денежные потоки (в т.ч. из OCR-текстов фото: переводы, чеки, экраны банков)
    "перевод", "переводы", "зачисление", "пополнение",
    "оплата", "чек", "платёж", "платеж", "выписка",
}

_WORDS_POSITIVE = {
    "отлично", "здорово", "супер", "класс", "прекрасно",
    "успех", "достижение", "рост", "вырос", "победа",
    "благодарю", "спасибо", "чудесно", "восхитительно",
    "план", "цель", "достиг", "получилось",
}

_WORDS_DEBT_RISK = {
    "кредит", "кредита", "кредиты", "кредитов",
    "долг", "долга", "долги", "задолженность",
    "микрозайм", "микрозаймы",
    "просрочка", "просрочк",
    "коллектор", "коллекторы",
    "займ", "займы",
}

_WORDS_GAMBLING_RISK = {
    "казино", "ставки", "ставок", "ставочк",
    "лотерея", "лотереи", "лото",
    "слоты", "слот",
    "беттинг",
    "без вложений", "быстрый доход", "легкие деньги",
    "заработок без", "пассивный доход за",
}

# Денежные поступления: «перевод + сумма» в одном сообщении (в т.ч. OCR-текст фото).
_TRANSFER_VERBS = {
    "перевод", "переводы", "зачисление", "зачисления",
    "пополнение", "поступило", "поступили", "оплата", "заработок",
}

# Числа с разделителями тысяч ("30.000", "5 000,50") или из 4+ цифр ("5000").
_AMOUNT_RE = re.compile(r"(?:\d+(?:[.,\s]\d{2,4})+|\d{4,})")


def _detect_money_transfer(channel: ParsedTelegramChannel) -> bool:
    """True, если хотя бы в одном сообщении упоминается перевод с суммой.

    Покрывает как текстовые посты («Перевод 30.000»), так и OCR-тексты фото
    со скринами банковских операций.
    """
    for msg in channel.messages:
        text = msg.text.lower()
        if any(verb in text for verb in _TRANSFER_VERBS) and _AMOUNT_RE.search(text):
            return True
    return False


# ---------- Вспомогательные функции ----------

def _corpus_stats(channel: ParsedTelegramChannel) -> tuple[str, int, int]:
    """Объединяет текст всех сообщений в корпус.

    Возвращает (corpus_lower, total_words, total_messages).
    """
    corpus = " ".join(msg.text for msg in channel.messages).lower()
    words = corpus.split()
    return corpus, len(words), len(channel.messages)


def _count_hits(corpus: str, vocabulary: set[str]) -> int:
    """Подсчитывает количество вхождений слов словаря в корпус."""
    hits = 0
    for word in vocabulary:
        hits += corpus.count(word)
    return hits


def _post_regularity_score(channel: ParsedTelegramChannel) -> float:
    """Оценка регулярности постов по среднему интервалу между датами.

    Возвращает 0.0–1.0: 1.0 = идеальная регулярность (ежедневно),
    0.0 = нет дат или всего 1 пост.
    """
    dates = [msg.date for msg in channel.messages if msg.date is not None]
    if len(dates) < 2:
        return 0.0
    sorted_dates = sorted(dates)
    intervals = [
        (sorted_dates[i] - sorted_dates[i - 1]).total_seconds() / 86400.0
        for i in range(1, len(sorted_dates))
    ]
    if not intervals:
        return 0.0
    mean_interval = float(np.mean(intervals))
    # Идеально — ежедневно (~1 день), плохо — раз в 14+ дней.
    # Нормализуем: 1 день → 1.0, 14 дней → 0.0, > 14 → 0.0.
    score = max(0.0, 1.0 - (mean_interval - 1.0) / 13.0)
    return float(np.clip(score, 0.0, 1.0))


# ---------- Основные функции ----------

def _heuristic_evidence(channel: ParsedTelegramChannel) -> TelegramScoringEvidence:
    """Собирает доказательства по словарным эвристикам (fallback-путь)."""
    corpus, _total_words, _total_messages = _corpus_stats(channel)
    return TelegramScoringEvidence(
        work_hits=_count_hits(corpus, _WORDS_WORK),
        fin_hits=_count_hits(corpus, _WORDS_FINANCE),
        pos_hits=_count_hits(corpus, _WORDS_POSITIVE),
        debt_hits=_count_hits(corpus, _WORDS_DEBT_RISK),
        gambling_hits=_count_hits(corpus, _WORDS_GAMBLING_RISK),
        has_money_transfer=_detect_money_transfer(channel),
        transfers_summary="",
    )


def _score_from_evidence(
    channel: ParsedTelegramChannel,
    evidence: TelegramScoringEvidence,
) -> TelegramScoringResult:
    """Считает скоринг и портрет по доказательствам.

    Единая формула для словарных эвристик и LLM-анализа. Возвращает
    TelegramScoringResult с оценкой вклада (0–100), позитивными сигналами,
    факторами риска, метриками портрета (0–10) и текстом отчёта.
    TG-003 объединит этот результат со стейтмент-оценкой.
    """
    _corpus, total_words, total_messages = _corpus_stats(channel)

    work_hits = evidence["work_hits"]
    fin_hits = evidence["fin_hits"]
    pos_hits = evidence["pos_hits"]
    debt_hits = evidence["debt_hits"]
    gambling_hits = evidence["gambling_hits"]
    has_money_transfer = evidence["has_money_transfer"]

    # Если корпус пуст — нейтральная оценка без сигналов.
    if total_words == 0 or total_messages == 0:
        return TelegramScoringResult(
            score_contribution=50,
            positive_signals=[],
            risk_factors=[],
            stability_score=5,
            financial_literacy_score=5,
            responsibility_score=5,
            report_content="Недостаточно текстовых данных для анализа канала.",
        )

    positive_signals: list[str] = []
    risk_factors: list[str] = []
    raw_score = 50.0

    # ---------- Сигналы ----------

    # 1. Работа / занятость (+0 или +15)
    work_density = work_hits / max(total_words, 1)
    if work_hits >= 2 and work_density > 0.005:
        raw_score += 15.0
        positive_signals.append("Упоминания трудовой деятельности или проектов.")

    # 2. Финансовая грамотность (+0 или +10)
    fin_density = fin_hits / max(total_words, 1)
    if fin_hits >= 2 and fin_density > 0.005:
        raw_score += 10.0
        positive_signals.append("Финансовая осведомлённость: упоминания инвестиций, бюджета или накоплений.")

    # 2a. Подтверждённые денежные поступления: «перевод + сумма» (+0 или +10)
    if has_money_transfer:
        raw_score += 10.0
        positive_signals.append(
            "Подтверждённые денежные поступления: упоминания переводов с суммой."
        )

    # 3. Позитивная лексика (+0 или +5)
    if pos_hits >= 2:
        raw_score += 5.0
        positive_signals.append("Позитивный характер публикаций.")

    # 4. Риски: долги / кредиты (−0 или −15)
    if debt_hits >= 1:
        raw_score -= 15.0
        risk_factors.append("Упоминание кредитных обязательств или задолженностей.")

    # 5. Риски: азарт / спам (−0 или −20)
    if gambling_hits >= 1:
        raw_score -= 20.0
        risk_factors.append("Признаки азартной активности или спам-контента.")

    # ---------- Портретные метрики ----------

    regularity = _post_regularity_score(channel)

    # Стабильность (0–10): наличие работы + регулярность постов
    stability_raw = 0.0
    if work_hits >= 2:
        stability_raw += 5.0
    stability_raw += regularity * 5.0
    stability_score = int(np.clip(round(stability_raw), 0, 10))

    # Финансовая грамотность (0–10): финлексика, поступления + отсутствие рисков
    fin_raw = 0.0
    if fin_hits >= 2:
        fin_raw += 5.0
    if has_money_transfer:
        fin_raw += 3.0
    if debt_hits == 0 and gambling_hits == 0:
        fin_raw += 5.0
    elif debt_hits >= 2 or gambling_hits >= 2:
        fin_raw = max(0.0, fin_raw - 2.0)
    financial_literacy_score = int(np.clip(round(fin_raw), 0, 10))

    # Ответственность (0–10): общая оценка
    responsibility_raw = (stability_score + financial_literacy_score) / 2.0
    if risk_factors:
        responsibility_raw = max(0.0, responsibility_raw - len(risk_factors))
    responsibility_score = int(np.clip(round(responsibility_raw), 0, 10))

    # ---------- Отчёт ----------
    report_parts = [
        f"Анализ канала @{channel.username}: {total_messages} сообщений, ~{total_words} слов.",
    ]
    if positive_signals:
        report_parts.append(f"Позитивные сигналы: {'; '.join(positive_signals)}")
    if evidence["transfers_summary"]:
        report_parts.append(f"Распознанные переводы: {evidence['transfers_summary']}.")
    if risk_factors:
        report_parts.append(f"Факторы риска: {'; '.join(risk_factors)}")
    if not positive_signals and not risk_factors:
        report_parts.append("Выраженных позитивных сигналов или факторов риска не обнаружено.")
    report_content = " ".join(report_parts)

    return TelegramScoringResult(
        score_contribution=int(np.clip(round(raw_score), 0, 100)),
        positive_signals=positive_signals,
        risk_factors=risk_factors,
        stability_score=stability_score,
        financial_literacy_score=financial_literacy_score,
        responsibility_score=responsibility_score,
        report_content=report_content,
    )


def score_telegram(channel: ParsedTelegramChannel) -> TelegramScoringResult:
    """Рассчитывает оценку по данным Telegram-канала (словарные эвристики).

    Обёртка над единой формулой _score_from_evidence. LLM-аналог —
    telegram_llm.score_telegram_with_llm, которая при недоступности GigaChat
    откатывается именно на эту функцию.
    """
    return _score_from_evidence(channel, _heuristic_evidence(channel))
