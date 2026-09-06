from typing import TypedDict
import difflib
import json
import re

from gigachat import GigaChat

from app.core.config import settings
from app.schemas.telegram import ParsedTelegramChannel
from app.scoring.telegram_scoring import (
    TelegramScoringEvidence,
    TelegramScoringResult,
    _score_from_evidence,
    score_telegram,
)

# TG-002 (LLM): анализ текста канала через GigaChat (Сбер).
#
# Роли в пайплайне TG-002/TG-003:
#   * OCR фото  — Gemini (telegram_vision.py)
#   * Текст     — GigaChat (этот модуль): семантический анализ корпуса + NER
#   * Формула   — единая (telegram_scoring._score_from_evidence)
#
# Дизайн тот же, что у telegram_vision: «красивая деградация». Без
# Authorization Key, при сетевой ошибке, таймауте или невалидном JSON-ответе
# модуль возвращает none/откат на словарные эвристики score_telegram(),
# скоринг не ломается.

GIGACHAT_REQUEST_TIMEOUT = 60  # секунд на один анализ канала

# Лимиты корпуса: защита от слишком больших каналов — берём последние посты.
MAX_MESSAGES = 200
MAX_CHARS_PER_MESSAGE = 500

# Поля, которые обязаны присутствовать в JSON-ответе GigaChat.
_REQUIRED_INT_FIELDS = ("work_mentions", "finance_mentions",
                        "positive_mentions", "debt_mentions", "gambling_mentions")

# Порог схожести для нечёткого сопоставления ключей (GigaChat иногда
# печатает ключи с опечатками, например "finance_ments" вместо "finance_mentions").
_KEY_RATIO_THRESHOLD = 0.75

# Направление перевода: income — поступление (зарплата, перевод на счёт),
# expense — расход/списание (в т.ч. проигрыш), transfer — без явного направления.
_INCOME_DIRECTIONS = {"income", "transfer"}

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMChannelAnalysis(TypedDict):
    """Структурированный разбор корпуса, который делает GigaChat."""
    work_mentions: int
    finance_mentions: int
    positive_mentions: int
    debt_mentions: int
    gambling_mentions: int
    transfers: list[dict]  # [{date?, amount?, counterparty?, direction?}, ...]


def _build_corpus_for_llm(channel: ParsedTelegramChannel) -> tuple[str, int]:
    """Готовит компактный корпус для GigaChat: нумерованные посты с датами.

    Возвращает (corpus_text, total_messages_used).
    """
    posts: list[str] = []
    for msg in channel.messages[-MAX_MESSAGES:]:
        date_part = msg.date.strftime("%Y-%m-%d") if msg.date is not None else "(дата неизвестна)"
        text = " ".join(msg.text.split())
        if len(text) > MAX_CHARS_PER_MESSAGE:
            text = text[:MAX_CHARS_PER_MESSAGE] + "…"
        posts.append(f"{len(posts) + 1}. [{date_part}] {text}")
    return "\n".join(posts), len(posts)


# Промпт: модель классифицирует лексику и извлекает переводы как структурированный JSON.
def _build_analysis_prompt(channel: ParsedTelegramChannel, corpus: str, n_posts: int) -> str:
    return f"""Ты — аналитик сервиса кредитного скоринга. Оцени содержимое Telegram-канала @{channel.username} ({n_posts} постов ниже) с точки зрения кредитоспособности. Работай строго по фактам текста, без догадок.

Для каждой категории посчитай количество упоминаний:
- work_mentions: работа, проекты, зарплата, заказчики, карьера
- finance_mentions: инвестиции, бюджет, накопления, переводы, оплата, чеки
- positive_mentions: позитивные формулировки, успехи, достижения
- debt_mentions: кредиты, долги, микрозаймы, просрочки, коллекторы (0 если нет)
- gambling_mentions: казино, ставки, лотереи, «быстрый доход» (0 если нет)

Извлеки денежные потоки в поле transfers: массив объектов {{"date": "...", "amount": "сумма", "counterparty": "контрагент", "direction": "income|expense|transfer"}}, где direction: income — поступление (зарплата, пополнение, входящий перевод), expense — расход/списание (оплата покупки, проигрыш), transfer — перевод без явного направления.

Ответь ТОЛЬКО одним JSON-объектом без markdown и пояснений, вида:
{{"work_mentions": 0, "finance_mentions": 0, "positive_mentions": 0, "debt_mentions": 0, "gambling_mentions": 0, "transfers": []}}

Посты канала:
{corpus}"""


def _parse_llm_json(text: str) -> dict | None:
    """Извлекает первый JSON-объект из ответа. None при невозможности."""
    if not text:
        return None
    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        # Пробуем отрезать trailing-мусор после последней закрывающей скобки.
        try:
            data = json.loads(match.group(0)[: match.group(0).rfind("}") + 1])
        except (ValueError, IndexError):
            return None
    if not isinstance(data, dict):
        return None
    return data


def _normalize_key(key: str) -> str:
    """Приводит ключ к сопоставимому виду: строчные буквы без разделителей."""
    return re.sub(r"[^a-z]", "", key.lower())


def _fuzzy_int_value(data: dict, target: str) -> int | None:
    """Ищет числовой ключ по нечёткому совпадению имени. None, если не найден."""
    t = _normalize_key(target)
    best_key: str | None = None
    best_ratio = 0.0
    for key in data:
        normalized = _normalize_key(key)
        if not normalized:
            continue
        ratio = difflib.SequenceMatcher(None, t, normalized).ratio()
        if ratio > best_ratio:
            best_key, best_ratio = key, ratio
    if best_key is None or best_ratio < _KEY_RATIO_THRESHOLD:
        return None
    value = data[best_key]
    return value if isinstance(value, int) else None


def _transfer_is_expense(transfer: dict) -> bool:
    """True для расхода: направление expense или отрицательная сумма."""
    direction = str(transfer.get("direction") or "").strip().lower()
    if direction == "expense":
        return True
    amount = str(transfer.get("amount") or "").strip()
    return amount.startswith("-") or amount.startswith("−")


def _evidence_from_llm(data: dict) -> LLMChannelAnalysis | None:
    """Валидирует JSON от GigaChat и приводит к типизированному виду.

    Имена ключей сопоставляются нечётко (устойчивость к опечаткам LLM).
    None при нарушении схемы — вызывающий откатится на эвристики.
    """
    counts: dict[str, int] = {}
    for field in _REQUIRED_INT_FIELDS:
        value = _fuzzy_int_value(data, field)
        if value is None:
            return None
        counts[field] = max(0, value)

    transfers = data.get("transfers")
    if not isinstance(transfers, list):
        return None
    normalized_transfers: list[dict] = []
    for transfer in transfers:
        if isinstance(transfer, dict) and (
            str(transfer.get("amount") or "") or str(transfer.get("counterparty") or "")
        ):
            normalized_transfers.append(transfer)

    return LLMChannelAnalysis(
        work_mentions=counts["work_mentions"],
        finance_mentions=counts["finance_mentions"],
        positive_mentions=counts["positive_mentions"],
        debt_mentions=counts["debt_mentions"],
        gambling_mentions=counts["gambling_mentions"],
        transfers=normalized_transfers,
    )


_UNKNOWN_DATE_MARKS = {"не указано", "неизвестно", "н/д", "н.д.", "unknown"}


def _transfers_summary(transfer: dict) -> str:
    """«40 541,32 ₽» + направление/контрагент/дата, если известны."""
    parts = []
    amount = transfer.get("amount") or ""
    if amount:
        parts.append(f"{amount} ₽")
    direction = str(transfer.get("direction") or "").strip().lower()
    if direction == "expense":
        parts.append("(расход)")
    counterparty = transfer.get("counterparty") or ""
    if counterparty:
        parts.append(f"({counterparty})")
    date = str(transfer.get("date") or "").strip()
    if date and date.lower() not in _UNKNOWN_DATE_MARKS:
        parts.append(date)
    return " ".join(parts) or "сумма не распознана"


def _analyze_through_gigachat(client: GigaChat, channel: ParsedTelegramChannel) -> LLMChannelAnalysis | None:
    """Один запрос к GigaChat. None при любой ошибке API."""
    corpus, n_posts = _build_corpus_for_llm(channel)
    if n_posts == 0 or not corpus.strip():
        return None
    try:
        response = client.chat.create(
            payload={
                "model": settings.GIGACHAT_MODEL,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": "Ты строго возвращаешь валидный JSON без пояснений."},
                    {"role": "user", "content": _build_analysis_prompt(channel, corpus, n_posts)},
                ],
            }
        )
        text = (response.messages[0].content[0].text or "").strip()
    except Exception:
        # Любая ошибка GigaChat (авторизация, сеть, квота) не ломает скоринг.
        return None
    data = _parse_llm_json(text)
    if data is None:
        return None
    return _evidence_from_llm(data)


def build_gigachat_client() -> GigaChat | None:
    """Создаёт клиент GigaChat. None без Authorization Key или при ошибке."""
    if not settings.GIGACHAT_CREDENTIALS:
        return None
    try:
        return GigaChat(
            credentials=settings.GIGACHAT_CREDENTIALS,
            scope=settings.GIGACHAT_SCOPE,
            base_url=settings.GIGACHAT_BASE_URL,
            verify_ssl_certs=settings.GIGACHAT_VERIFY_SSL_CERTS,
            timeout=GIGACHAT_REQUEST_TIMEOUT,
        )
    except Exception:
        return None


def analyze_channel_semantics(
    channel: ParsedTelegramChannel,
    client: GigaChat | None = None,
) -> LLMChannelAnalysis | None:
    """Анализирует текст канала через GigaChat, на выходе — типизированные данные.

    None, если LLM недоступен (нет ключа, ошибка, невалидный ответ) или
    корпус пуст. Клиент не закрывается здесь: вызывающий отвечает за ресурс.
    """
    if client is None:
        client = build_gigachat_client()
    if client is None:
        return None
    return _analyze_through_gigachat(client, channel)


def score_telegram_with_llm(
    channel: ParsedTelegramChannel,
    client: GigaChat | None = None,
) -> TelegramScoringResult:
    """Скоринг канала с LLM-анализом и откатом на словарные эвристики.

    Если GigaChat недоступен или вернул невалидный результат — считаем
    через score_telegram() (текущее поведение без изменений).
    """
    analysis = analyze_channel_semantics(channel, client=client)
    if analysis is None:
        return score_telegram(channel)

    # Поступления — только приходные/нейтральные переводы; расходы
    # (проигрыш, оплата) не усиливают сигнал «денежные поступления».
    income_transfers = [
        t for t in analysis["transfers"] if not _transfer_is_expense(t)
    ]
    transfers_summary = " и ".join(
        _transfers_summary(t) for t in income_transfers[:10]
    )
    expenses = [t for t in analysis["transfers"] if _transfer_is_expense(t)]
    if expenses:
        expenses_summary = ", ".join(_transfers_summary(t) for t in expenses[:5])
        transfers_summary = (
            transfers_summary + " (расходы: " + expenses_summary + ")"
            if transfers_summary else "расходы: " + expenses_summary
        )

    evidence: TelegramScoringEvidence = TelegramScoringEvidence(
        work_hits=max(0, analysis["work_mentions"]),
        fin_hits=max(0, analysis["finance_mentions"]),
        pos_hits=max(0, analysis["positive_mentions"]),
        debt_hits=max(0, analysis["debt_mentions"]),
        gambling_hits=max(0, analysis["gambling_mentions"]),
        has_money_transfer=bool(income_transfers),
        transfers_summary=transfers_summary,
    )
    return _score_from_evidence(channel, evidence)