"""Deterministic memory-intent classification and bounded query expansion.

The planner is deliberately local and side-effect free.  It improves recall for
multi-clause and temporal questions without placing an LLM call on the prompt
critical path.  Callers remain responsible for ACL filtering and content guards.
"""
from __future__ import annotations

from datetime import date
import re
from typing import Any


_SPACE_RE = re.compile(r"\s+")
_CLAUSE_RE = re.compile(
    r"(?:[;!?]+|\s+(?:and|also|plus|then|while|but|as well as|и|а также|затем|потом|но)\s+)",
    re.IGNORECASE,
)
_TEMPORAL_RE = re.compile(
    r"\b(?:today|yesterday|tomorrow|current|currently|latest|recent|recently|"
    r"before|after|since|until|when|first|last|previous|now|"
    r"сегодня|вчера|завтра|текущ(?:ий|ая|ее|ие)|последн(?:ий|яя|ее|ие)|"
    r"недавн(?:о|ий|яя|ее)|когда|сначала|раньше|сейчас)\b",
    re.IGNORECASE,
)
# Russian prepositions need temporal complements: «с» can mean «with»,
# and «до» can be spatial. Validate calendar tokens rather than their shape.
_RU_ENDPOINT_RE = re.compile(r"\b(?:с|со|до|после)\s+", re.IGNORECASE)
_RU_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_RU_NUMERIC_DATE_RE = re.compile(
    r"(?:(?P<iso_year>\d{4})-(?P<iso_month>\d{1,2})-(?P<iso_day>\d{1,2})|"
    r"(?P<day>\d{1,2})(?P<sep>[./-])(?P<month>\d{1,2})"
    r"(?:(?P=sep)(?P<year>\d{4}|\d{2}))?)(?![\w./-])"
)
_RU_NAMED_DATE_RE = re.compile(
    r"(?:(?P<day>\d{1,2})\s+)?(?P<month>" + "|".join(_RU_MONTHS) +
    r")\b(?:\s+(?P<year>\d{4})(?!\d))?", re.IGNORECASE,
)
_RU_YEAR_RE = re.compile(r"(?P<year>\d{1,4})(?![\w./-])")
_RU_YEAR_UNIT_RE = re.compile(r"^\s*(?:года|год|г\.?)(?!\w)", re.IGNORECASE)
_RU_CALENDAR_TAIL_RE = re.compile(
    r"^(?:$|[,;!?)\]]|(?:по|до|после|и|включительно)\b)", re.IGNORECASE,
)
_RU_MEASUREMENT_UNIT_RE = re.compile(
    r"(?:(?:милли|санти|кило)?(?:литр|метр|грамм|ватт|вольт|ньютон|джоул)\w*|"
    r"(?:микро|милли|кило|мега)?паскал\w*|секунд\w*|минут\w*|час\w*|"
    r"мл|л|мм|см|км|м|мг|кг|г|мс|с|мин|ч|[кмг]?па)", re.IGNORECASE,
)
_RU_RELATIVE_RE = re.compile(
    r"(?:понедельника|вторника|среды|четверга|пятницы|субботы|воскресенья|"
    r"сегодня|вчера|завтра|вчерашнего\s+дня|сегодняшнего\s+дня|завтрашнего\s+дня|"
    r"(?:прошл(?:ого|ой)|эт(?:ого|ой)|позапрошл(?:ого|ой)|будущ(?:его|ей)|следующ(?:его|ей))\s+"
    r"(?:года|месяца|недели|зимы|весны|лета|осени)|"
    r"тех\s+пор|начала\s+(?:года|месяца|недели))\b", re.IGNORECASE,
)
# Event-time endpoints are not calendar tokens; retain those separately.
_RU_EVENT_RE = re.compile(
    r"(?:(?:(?:момента|времени)\s+)?(?:запуск(?:а|ов)|перезапуск(?:а|ов)|установ(?:ки|ок)|"
    r"обновлени(?:я|й)|переезд(?:а|ов)|встреч(?:и)?|покуп(?:ки|ок)|релиз(?:а|ов)|авари(?:и|й)|"
    r"начала|окончани(?:я|й)|завершени(?:я|й))|того\s+как)\b", re.IGNORECASE,
)
_CURRENT_STATE_RE = re.compile(
    r"\b(?:current|currently|latest|now|still|active|today|"
    r"текущ(?:ий|ая|ее|ие)|последн(?:ий|яя|ее|ие)|сейчас|актуальн(?:ый|ая|ое|ые)|ещ[её])\b",
    re.IGNORECASE,
)
_PREFERENCE_RE = re.compile(
    r"\b(?:prefer|preference|like|dislike|favorite|favourite|always|never|"
    r"предпочита\w*|нравит\w*|любим\w*|не люблю|всегда|никогда)\b",
    re.IGNORECASE,
)
_PROCEDURE_RE = re.compile(
    r"\b(?:how|steps?|procedure|workflow|runbook|install|configure|fix|deploy|"
    r"как|шаг|процедур|процесс|инструкц|настро|установ|исправ|развер)\w*",
    re.IGNORECASE,
)
_NEGATIVE_PREMISE_RE = re.compile(
    r"\b(?:not|no|never|neither|nor|without|cannot|didnt|isnt|wasnt|denied|deny|forbid\w*|"
    r"forbad\w*|forbidden|refus\w*|не|ни|нет|никогда|ничего|нельзя|без|"
    r"запрет\w*|запрещ\w*|отказ\w*|разве\s+не|точно\s+ли)\b|"
    r"\b\w+n['’]t\b",
    re.IGNORECASE,
)
_QUESTION_PREFIX_RE = re.compile(
    r"^\s*(?:(?:please\s+)?(?:tell|remind|show)\s+me\s+|"
    r"(?:do\s+you\s+remember|what\s+do\s+you\s+remember\s+about|"
    r"what\s+did\s+i\s+(?:say|tell\s+you)\s+about|"
    r"can\s+you\s+recall)\s+|"
    r"(?:пожалуйста[, ]+)?(?:напомни|расскажи|покажи)\s+(?:мне\s+)?|"
    r"(?:ты\s+)?помнишь\s+|что\s+(?:я\s+)?(?:говорил|рассказывал)\s+(?:тебе\s+)?(?:о|про)\s+)",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r"[\"“”«»]([^\"“”«»]{3,160})[\"“”«»]")


def _clean(value: str, max_chars: int = 500) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip(" \t\r\n,.;:!?-")[:max_chars]


def _calendar_tail_ok(tail: str, calendar_token: bool = False, partial_numeric: bool = False,
                      calendar_notation: bool = False, calendar_context: bool = False) -> bool:
    """Separate confirmed calendar endpoints from ambiguous numeric measures."""
    year_unit = _RU_YEAR_UNIT_RE.match(tail)
    # A partial date-shaped decimal cannot acquire a year from a gram suffix.
    # Bare «г» needs a four-digit year; explicit year words/«г.» remain valid.
    if year_unit and not calendar_token and (
        partial_numeric or (not calendar_notation and year_unit[0].strip().casefold() == "г")
    ):
        return False
    tail = _RU_YEAR_UNIT_RE.sub("", tail, count=1).lstrip()
    # A validated named/full date or explicit year has its own calendar unit.
    # A separate quantity, including decimals/fractions, cannot revoke it.
    if calendar_token or year_unit:
        return bool(_RU_CALENDAR_TAIL_RE.match(tail))
    continuation = re.match(
        r"^(?:,\s*|(?:и|по|до|после)\s+)(?=(?:(?:с|со|до|после)\s+)?\d)",
        tail, re.IGNORECASE,
    )
    if continuation:
        following = re.sub(
            r"^(?:с|со|до|после)\s+", "", tail[continuation.end():],
            count=1, flags=re.IGNORECASE,
        )
        next_year = _RU_YEAR_RE.match(following)
        next_calendar = (
            _RU_NUMERIC_DATE_RE.match(following) or _RU_NAMED_DATE_RE.match(following)
            or (next_year and (len(next_year["year"]) == 4
                               or _RU_YEAR_UNIT_RE.match(following[next_year.end():])))
        )
        if next_calendar and _ru_calendar_endpoint(following, calendar_context=calendar_context):
            return True
        count = re.match(r"^\d+\s+(?P<noun>[^\W\d_]+)\b", following)
        if not partial_numeric or not calendar_notation or not count:
            return False
        # A partial date-shaped number can share the following measurement unit;
        # instrumental nouns and physical/time units do not establish a date.
        return not (_RU_MEASUREMENT_UNIT_RE.fullmatch(count["noun"]) or re.search(
            r"(?:ами|ями|ом|ем|ой|ей|ою|ею)$", count["noun"], re.IGNORECASE,
        ))
    return bool(_RU_CALENDAR_TAIL_RE.match(tail))


def _ru_calendar_endpoint(text: str, *, calendar_context: bool = False) -> bool:
    numeric = _RU_NUMERIC_DATE_RE.match(text)
    named = _RU_NAMED_DATE_RE.match(text)
    year_only = _RU_YEAR_RE.match(text)
    if numeric:
        year = numeric["iso_year"] or numeric["year"]
        # Undated February 29 is a possible calendar endpoint. Two-digit years
        # use 2000..2099 solely for leap validation, not to rewrite the query.
        year = int(year) if year else 2000
        if numeric["year"] and len(numeric["year"]) == 2:
            year += 2000
        month = int(numeric["iso_month"] or numeric["month"])
        day = int(numeric["iso_day"] or numeric["day"])
        end = numeric.end()
    elif named:
        year = int(named["year"]) if named["year"] else 2000
        month = _RU_MONTHS.index(named["month"].casefold()) + 1
        day = int(named["day"]) if named["day"] else 1
        end = named.end()
    elif year_only:
        year, month, day = int(year_only["year"]), 1, 1
        end = year_only.end()
    else:
        return False
    try:
        date(year, month, day)
    except ValueError:
        return False
    full_numeric = bool(numeric and (numeric["iso_year"] or numeric["year"]))
    # A partial numeric endpoint may also be a decimal or fraction.
    # A separator alone is not calendar evidence; require date notation or
    # a preceding calendar frame in the same clause, never a unit allowlist.
    calendar_notation = bool(
        (year_only and len(year_only["year"]) == 4)
        or (numeric and not full_numeric and (
            calendar_context or numeric["day"].startswith("0")
            or numeric["month"].startswith("0")
        ))
    )
    return _calendar_tail_ok(
        text[end:], calendar_token=bool(named or full_numeric),
        partial_numeric=bool(numeric and not full_numeric),
        calendar_notation=calendar_notation, calendar_context=calendar_context,
    )


def _has_ru_temporal_endpoint(text: str) -> bool:
    for endpoint in _RU_ENDPOINT_RE.finditer(text):
        complement = text[endpoint.end():]
        # Context belongs to this endpoint's preceding clause, not to a later
        # archive mention or a separate unrelated clause.
        prefix = _CLAUSE_RE.split(text[:endpoint.start()].rsplit(".", 1)[-1])[-1]
        calendar_context = bool(re.search(
            r"\b(?:архив\w*|дат(?:а|ы|у|е|ой|ам|ами|ах)?|календар\w*|"
            r"запис\w*|журнал\w*|заметк\w*|период\w*)\b", prefix, re.IGNORECASE,
        ))
        if (_ru_calendar_endpoint(complement, calendar_context=calendar_context) or _RU_RELATIVE_RE.match(complement)
                or _RU_EVENT_RE.match(complement)):
            return True
    return False


def classify_memory_intent(query: str) -> dict[str, Any]:
    """Classify retrieval intent with transparent multilingual rules."""
    text = _clean(query)
    clauses = [part for part in (_clean(v) for v in _CLAUSE_RE.split(text)) if len(part) >= 3]
    temporal = bool(_TEMPORAL_RE.search(text) or _has_ru_temporal_endpoint(text))
    current_state = bool(_CURRENT_STATE_RE.search(text))
    preference = bool(_PREFERENCE_RE.search(text))
    procedure = bool(_PROCEDURE_RE.search(text))
    negative_premise = bool(_NEGATIVE_PREMISE_RE.search(text))
    multi_hop = len(clauses) > 1 or len(_QUOTED_RE.findall(text)) > 1
    if preference:
        primary = "preference"
    elif procedure:
        primary = "procedural"
    elif current_state:
        primary = "current_state"
    elif temporal:
        primary = "temporal"
    elif multi_hop:
        primary = "multi_hop"
    else:
        primary = "factual"
    return {
        "primary": primary,
        "temporal": temporal,
        "current_state": current_state,
        "multi_hop": multi_hop,
        "preference": preference,
        "procedural": procedure,
        "negative_premise": negative_premise,
        "deep_recommended": bool(multi_hop or temporal or negative_premise),
    }


def expand_memory_queries(query: str, mode: str = "auto", max_queries: int | None = None) -> list[str]:
    """Return stable, de-duplicated retrieval queries under a hard size cap.

    ``fast`` keeps the original only. ``auto`` adds up to two useful variants,
    while ``deep`` may add clause and quoted-phrase variants.  Expansion never
    invents entities or facts that are absent from the caller's query.
    Negative or uncertain-polarity premises keep only the cleaned original:
    clause/quote extraction cannot safely propagate a shared negative predicate.
    This deliberately trades expansion recall for polarity precision.
    """
    mode = str(mode or "auto").strip().lower()
    if mode not in {"fast", "auto", "deep"}:
        raise ValueError("mode must be one of: fast, auto, deep")
    original = _clean(query)
    if not original:
        return []
    cap = max_queries if max_queries is not None else {"fast": 1, "auto": 3, "deep": 5}[mode]
    cap = max(1, min(int(cap), 8))
    values: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        normalized = _clean(value)
        key = normalized.casefold()
        if len(normalized) >= 3 and key not in seen and len(values) < cap:
            seen.add(key)
            values.append(normalized)

    add(original)
    if mode == "fast" or len(values) >= cap:
        return values
    if _NEGATIVE_PREMISE_RE.search(original):
        return values

    content = _clean(_QUESTION_PREFIX_RE.sub("", original))
    if content and content.casefold() != original.casefold():
        add(content)

    intent = classify_memory_intent(original)
    if intent["multi_hop"] or mode == "deep":
        for clause in _CLAUSE_RE.split(content or original):
            clause = _clean(clause)
            # Very short fragments make broad FTS OR queries and hurt precision.
            if len(clause) >= 5:
                add(clause)

    if mode == "deep":
        for quoted in _QUOTED_RE.findall(original):
            add(quoted)

    return values
