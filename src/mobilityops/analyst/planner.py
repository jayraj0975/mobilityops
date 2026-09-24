"""Turning a question into tool calls.

``RulePlanner`` is deterministic: keyword intents, and entity parsing (zones, dates, periods, hour
windows, holidays). It never guesses silently: every default it applies (for example "no period
given, using the last 7 days") is returned as an *assumption* that the answer states. When it cannot
tell what is being asked it returns a clarification, not a guess.

``LLMPlanner`` (llm.py) can replace it when a key is configured. Either way the planner only
*selects tools and arguments*; it never writes numbers, and it never sees tool outputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

from mobilityops.analyst.glossary import GLOSSARY

MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for m in names
}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10}  # fmt: skip
_STOP = {
    "city", "citywide", "zone", "zones", "area", "areas", "pickups", "pickup", "taxi", "taxis",
    "demand", "week", "month", "last", "day", "days", "east", "west", "north", "south", "park",
    "side", "square", "airport", "most", "busiest", "top", "which", "what", "where", "when",
    "how", "many", "much", "were", "was", "the", "for", "and", "with", "from", "that", "this",
    "about", "there", "their", "than", "have", "between", "during", "trips", "forecast",
    "anomaly", "anomalies", "weather", "rain", "snow", "evening", "morning", "afternoon",
}  # fmt: skip


@dataclass(frozen=True)
class PlanningContext:
    data_first: date
    data_last: date  # inclusive
    zones: pd.DataFrame
    eval_first: date | None = None
    eval_last: date | None = None

    def holidays(self) -> dict[str, date]:
        cal = USFederalHolidayCalendar()
        found = cal.holidays(
            start=pd.Timestamp(self.data_first).to_pydatetime(),
            end=pd.Timestamp(self.data_last).to_pydatetime(),
            return_name=True,
        )
        out: dict[str, date] = {}
        for ts, name in zip(pd.DatetimeIndex(found.index), found.to_numpy(), strict=True):
            d = ts.date()
            nm = str(name).lower().replace("\u2019", "'")
            out[nm] = d
            for alias, keys in (
                ("memorial day", ("memorial",)),
                ("mlk day", ("martin luther king",)),
                ("presidents day", ("washington",)),
                ("new year", ("new year",)),
            ):
                if any(k in nm for k in keys):
                    out[alias] = d
        return out


@dataclass
class PlannedCall:
    name: str
    args: dict[str, Any]


@dataclass
class Plan:
    intent: str
    calls: list[PlannedCall] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    clarification: str | None = None


class Planner(Protocol):
    name: str

    def plan(self, question: str, ctx: PlanningContext) -> Plan: ...


# ---------------------------------------------------------------------------- entities
def find_zone(text: str, zones: pd.DataFrame) -> tuple[int | None, list[str]]:
    """Return (zone id, []) if one zone is meant; (None, candidates) if ambiguous; (None, []) if none."""
    m = re.search(r"\b(?:zone|location)(?:\s+id)?\s*#?\s*(\d{1,3})\b", text, re.I)
    if m:
        zid = int(m.group(1))
        ok = (zones["location_id"] == zid).any()
        return (zid, []) if ok else (None, [f"zone id {zid} does not exist"])
    names = {int(r["location_id"]): str(r["zone"]) for r in zones.to_dict("records")}
    low = text.lower().replace("\u2019", "'")
    exact = [i for i, nm in names.items() if nm.lower() in low]
    if exact:
        best = max(exact, key=lambda i: len(names[i]))
        return best, []
    tokens = re.findall(r"[a-z0-9'./&-]+", low)
    for size in range(min(5, len(tokens)), 0, -1):
        for i in range(len(tokens) - size + 1):
            gram = " ".join(tokens[i : i + size])
            if len(gram) < 5 or all(t in _STOP for t in tokens[i : i + size]):
                continue
            if size == 1 and gram in _STOP:
                continue
            hits = [i2 for i2, nm in names.items() if gram in nm.lower()]
            if len(hits) == 1:
                return hits[0], []
            if 1 < len(hits) <= 6:
                return None, [names[h] for h in hits]
    return None, []


def _to_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str, ctx: PlanningContext) -> list[date]:
    """Dates in order of appearance: ISO, 'May 27', '27 May', holiday names."""
    low = text.lower().replace("\u2019", "'")
    found: list[tuple[int, date]] = []
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", low):
        d = _to_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            found.append((m.start(), d))
    year = ctx.data_last.year
    for m in re.finditer(
        rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", low
    ):
        d = _to_date(int(m.group(3) or year), MONTHS[m.group(1)], int(m.group(2)))
        if d:
            found.append((m.start(), d))
    for m in re.finditer(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_RE})\b(?:,?\s+(\d{{4}}))?", low
    ):
        d = _to_date(int(m.group(3) or year), MONTHS[m.group(2)], int(m.group(1)))
        if d:
            found.append((m.start(), d))
    for name, d in ctx.holidays().items():
        i = low.find(name)
        if i >= 0:
            found.append((i, d))
    seen: set[date] = set()
    out: list[date] = []
    for _, d in sorted(found):
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


@dataclass(frozen=True)
class Period:
    start: date
    end_exclusive: date
    text: str  # how it was understood, for the assumption line


def _clip(start: date, end_excl: date, ctx: PlanningContext) -> tuple[date, date]:
    return max(start, ctx.data_first), min(end_excl, ctx.data_last + timedelta(days=1))


def parse_period(text: str, ctx: PlanningContext, *, bare_month: bool = False) -> Period | None:
    low = text.lower().replace("\u2019", "'")
    one_day = timedelta(days=1)
    dates = find_dates(text, ctx)
    ranged = re.search(r"\b(from|between|through|until|to)\b|\s-\s", low)
    if len(dates) >= 2 and ranged:
        a, b = sorted(dates[:2])
        return Period(a, b + one_day, f"{a} to {b}")
    if len(dates) == 1:
        d = dates[0]
        return Period(d, d + one_day, f"{d}")
    m = re.search(rf"\b(?:in|during|for|of)?\s*\b({_MONTH_RE})\b(?:\s+(\d{{4}}))?", low)
    if m and re.search(rf"\b(in|during|for|of|month of)\s+({_MONTH_RE})\b", low):
        mm = re.search(rf"\b(?:in|during|for|of)\s+({_MONTH_RE})\b(?:\s+(\d{{4}}))?", low)
        if mm:
            y = int(mm.group(2) or ctx.data_last.year)
            mo = MONTHS[mm.group(1)]
            s = date(y, mo, 1)
            e = date(y + (mo == 12), mo % 12 + 1, 1)
            s, e = _clip(s, e, ctx)
            if s < e:
                return Period(s, e, f"{s} to {e - one_day}")
    if bare_month:
        bm = re.search(rf"\b({_MONTH_RE})\b(?:\s+(\d{{4}}))?", low)
        if bm:
            y = int(bm.group(2) or ctx.data_last.year)
            mo = MONTHS[bm.group(1)]
            s0, e0 = _clip(date(y, mo, 1), date(y + (mo == 12), mo % 12 + 1, 1), ctx)
            if s0 < e0:
                return Period(s0, e0, f"{s0} to {e0 - one_day}")
    m = re.search(
        r"\blast\s+(\d+|one|two|three|four|five|six|seven|ten)\s+(day|week|month)s?\b", low
    )
    if m:
        k = int(m.group(1)) if m.group(1).isdigit() else _NUM_WORDS[m.group(1)]
        days = k * {"day": 1, "week": 7, "month": 30}[m.group(2)]
        e = ctx.data_last + one_day
        s = max(ctx.data_first, e - timedelta(days=days))
        return Period(s, e, f"the last {days} days of data ({s} to {ctx.data_last})")
    if re.search(r"\b(last|past|previous|this)\s+week\b", low):
        e = ctx.data_last + one_day
        return Period(
            e - timedelta(days=7),
            e,
            f"the last 7 days of data ({e - timedelta(days=7)} to {ctx.data_last})",
        )
    if re.search(r"\b(last|past|previous|this)\s+month\b", low):
        e = ctx.data_last + one_day
        s = max(ctx.data_first, e - timedelta(days=30))
        return Period(s, e, f"the last 30 days of data ({s} to {ctx.data_last})")
    if re.search(r"\byesterday\b", low):
        d = ctx.data_last
        return Period(d, d + one_day, f"{d} (the last day of data)")
    if re.search(r"\b(overall|in total|all data|whole|entire|so far|all time|ever)\b", low):
        return Period(
            ctx.data_first,
            ctx.data_last + one_day,
            f"all data ({ctx.data_first} to {ctx.data_last})",
        )
    return None


def find_window(text: str) -> tuple[int, int] | None:
    low = text.lower()
    m = re.search(
        r"\b(\d{1,2})(?::00)?\s*(am|pm)?\s*(?:-|to|until|through)\s*(\d{1,2})(?::00)?\s*(am|pm)?\b",
        low,
    )
    if m and (m.group(2) or m.group(4) or ":" in m.group(0)):

        def h(v: str, ap: str | None) -> int:
            x = int(v)
            if ap == "pm" and x < 12:
                x += 12
            if ap == "am" and x == 12:
                x = 0
            return x

        end_ap = m.group(4) or m.group(2)
        a, b = h(m.group(1), m.group(2) or (end_ap if m.group(4) else None)), h(m.group(3), end_ap)
        if 0 <= a < b <= 24:
            return a, b
    for key, w in (
        ("morning", (7, 10)), ("rush hour", (17, 20)), ("evening", (17, 20)),
        ("after work", (17, 20)), ("midday", (11, 14)), ("lunch", (11, 14)),
        ("afternoon", (12, 16)), ("night", (21, 24)),
    ):  # fmt: skip
        if key in low:
            return w
    return None


_NOT_PLACES = {
    "nyc", "new york", "new york city", "manhattan", "brooklyn", "queens", "bronx", "the bronx",
    "staten island", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "wape", "mae", "rmse", "lightgbm", "the", "a", "an", "my", "our", "this", "that", "i", "it",
}  # fmt: skip


def unknown_place(question: str, ctx: PlanningContext) -> str | None:
    """A capitalised place named after in/at/near/for that matches no zone, month or holiday.

    Answering a citywide question when the user asked about somewhere else would be misleading, so
    the planner asks instead.
    """
    holiday_words = {w for name in ctx.holidays() for w in name.split()}
    for m in re.finditer(
        r"\b(?:in|at|near|around)\s+(?:the\s+)?([a-z][\w'./&-]*(?:\s+[a-z][\w'./&-]*){0,2})\s+"
        r"(?:zone|area|neighbou?rhood|district)\b",
        question,
        re.I,
    ):
        place = m.group(1).strip()
        if place.lower() not in _NOT_PLACES and find_zone(place, ctx.zones) == (None, []):
            return place
    for m in re.finditer(
        r"\b(?:in|at|near|around|for|of)\s+((?:[A-Z][\w'.&/-]*\s?){1,4})"
        r"|\b(?:did|does|do|was|were|is|are|has|have)\s+((?:[A-Z][\w'.&/-]*\s?){1,4})"
        r"\s+(?:have|get|got|see|saw|record|had|recorded|look|looking)\b",
        question,
    ):
        place = (m.group(1) or m.group(2)).strip()
        low = place.lower()
        first = low.split()[0]
        if low in _NOT_PLACES or first in MONTHS or first in holiday_words or first in _NOT_PLACES:
            continue
        if find_dates(place, ctx) or find_zone(place, ctx.zones) != (None, []):
            continue
        return place
    return None


_DEMAND_WORDS = (
    r"\bdemand", r"\bpickups?", r"\btrips?", r"\btaxis?", r"\bride", r"\bbusy", r"\bbusiest",
    r"\baffect", r"\beffect", r"\bimpact", r"\breduc", r"\bincreas", r"\bcompare",
    r"\b(drop|surge|spike|dip|fell|fall|rose|low|high)\b", r"\banomal", r"\bunusual",
)  # fmt: skip


def _has(low: str, *pats: str) -> bool:
    return any(re.search(p, low) for p in pats)


def _top_n(low: str, default: int = 5) -> int:
    m = re.search(r"\b(?:top|first|best)\s+(\d+|" + "|".join(_NUM_WORDS) + r")\b", low)
    if m:
        v = m.group(1)
        return min(20, int(v) if v.isdigit() else _NUM_WORDS[v])
    m = re.search(
        r"\b(\d+|" + "|".join(_NUM_WORDS) + r")\s+(?:busiest|quietest|most|least|top)\b", low
    )
    if m:
        v = m.group(1)
        return min(20, int(v) if v.isdigit() else _NUM_WORDS[v])
    return default


def _glossary_term(low: str) -> str | None:
    m = re.search(
        r"\b(?:what(?:'s| is| are| does)|define|meaning of|explain(?: the term)?)\s+(?:an? |the )?([a-z\- ]{2,40}?)(?:\s+mean)?\s*\??$",
        low.strip(),
    )
    if not m:
        return None
    term = m.group(1).strip()
    aliases = {"interval": "prediction interval", "walk forward": "walk-forward", "walk-forward evaluation": "walk-forward", "event score": "event score", "sample": "sample data", "synthetic data": "sample data", "test data": "sample data", "daylight saving": "dst", "daylight saving time": "dst", "drop": "drop", "surge": "surge"}  # fmt: skip
    term = aliases.get(term, term)
    return term if term in GLOSSARY else None


# ------------------------------------------------------------------------- rule planner
class RulePlanner:
    name = "deterministic"

    def plan(self, question: str, ctx: PlanningContext) -> Plan:
        low = question.lower().replace("\u2019", "'")
        assumptions: list[str] = []

        def period(default: str = "last7") -> Period:
            p = parse_period(question, ctx)
            if p is not None:
                s, e = _clip(p.start, p.end_exclusive, ctx)
                if s >= e:
                    assumptions.append(
                        f"The period you asked for ({p.text}) has no data (data covers "
                        f"{ctx.data_first} to {ctx.data_last}), so I used all data instead."
                    )
                    return Period(
                        ctx.data_first,
                        ctx.data_last + timedelta(days=1),
                        f"all data ({ctx.data_first} to {ctx.data_last})",
                    )
                return Period(s, e, p.text)
            if default == "all":
                p2 = Period(
                    ctx.data_first,
                    ctx.data_last + timedelta(days=1),
                    f"all data ({ctx.data_first} to {ctx.data_last})",
                )
            else:
                e = ctx.data_last + timedelta(days=1)
                s = max(ctx.data_first, e - timedelta(days=7))
                p2 = Period(s, e, f"the last 7 days of data ({s} to {ctx.data_last})")
            assumptions.append(f"No period was given, so I used {p2.text}.")
            return p2

        zone_id, candidates = find_zone(question, ctx.zones)
        zone_named = zone_id is not None or bool(candidates)
        low_q = question.lower()
        if _has(
            low_q,
            r"\brain",
            r"\bsnow",
            r"\bfreez",
            r"\bweather\b",
            r"\bstorm",
            r"\bprecip",
            r"\bwet\b",
            r"\bdrizzl",
            r"\bdownpour",
            r"\bblizzard",
        ) and not _has(low_q, *_DEMAND_WORDS):
            return Plan(
                "clarify",
                clarification="I do not provide weather information. I can compare taxi demand on rainy, snowy or freezing days with other days; try asking how rain relates to demand.",
            )
        if (
            zone_id is None
            and not candidates
            and re.search(r"\b(manhattan|brooklyn|queens|the bronx|bronx|staten island)\b", low)
        ):
            return Plan(
                "clarify",
                clarification=(
                    "I report demand by taxi zone (a neighbourhood-sized area), not by borough. "
                    "Ask about a specific zone, for example 'East Village' or 'JFK Airport', or "
                    "ask for the busiest zones."
                ),
            )
        if zone_id is None and not candidates:
            place = unknown_place(question, ctx)
            if place:
                return Plan(
                    "clarify",
                    clarification=f"I could not find a taxi zone matching '{place}'. Try the name of a TLC zone, such as 'East Village' or 'JFK Airport', or a zone id.",
                )

        def clarify_zone() -> Plan | None:
            if zone_id is None and candidates:
                return Plan(
                    "clarify",
                    clarification="Which zone do you mean: " + "; ".join(candidates) + "?",
                    assumptions=assumptions,
                )
            return None

        # ---- meta questions ------------------------------------------------------
        term = _glossary_term(low)
        if term:
            return Plan("glossary", [PlannedCall("get_glossary", {"term": term})])
        if _has(
            low,
            r"\bwhat data\b",
            r"\bhow much data\b",
            r"\bdate range\b",
            r"\bwhat period\b",
            r"\bis (this|the data) (real|synthetic|fake)\b",
            r"\b(real|synthetic|sample) data\b.*\?",
            r"\bwhich (data|dataset)\b",
            r"\bwhat (dates|days) (does|do|is|are)\b",
        ) or (
            _has(low, r"\bhow many (zones|trips)\b")
            and not zone_named
            and parse_period(question, ctx) is None
        ):
            return Plan("overview", [PlannedCall("get_data_overview", {})])
        if _has(
            low,
            r"\b(how )?accura",
            r"\bforecast (error|quality|performance)\b",
            r"\bwape\b",
            r"\bmae\b",
            r"\brmse\b",
            r"\bhow good\b",
            r"\bbaselines?\b",
            r"\bcan (i|we) trust\b",
            r"\bmodel (performance|quality)\b",
            r"\bhow reliable\b",
            r"\bbeat(s)? (the )?(baseline|naive)",
            r"\berror rate\b",
            r"\b(forecasts?|predictions?|model)\b.*\b(better|worse|beat|outperform)\w*\b.*\b(than|the)\b.*"
            r"\b(copy|copying|last week|yesterday|naive|baseline|seasonal|simple|average)",
            r"\b(better|worse) than (just )?(copy|copying|guessing|last week|yesterday|the average)",
        ) or (
            _has(
                low,
                r"\bhow (wrong|far off|often wrong|close)\b.*\b(forecasts?|predictions?|model)\b",
            )
            and not zone_named
            and not find_dates(question, ctx)
        ):
            return Plan("model_performance", [PlannedCall("get_model_performance", {})])
        if (
            _has(low, r"\b(repositioning|rebalancing|reposition|rebalance)\b")
            and _has(
                low,
                r"\b(result|finding|backtest|benefit|help|worth|gain|improve|how much|effective|effect)\b",
            )
            and not _has(low, r"\bsimulate\b", r"\bwhat if\b", r"\b(on|for)\s+\d{4}-\d{2}-\d{2}\b")
        ):
            return Plan("optimization_findings", [PlannedCall("get_optimization_findings", {})])
        # ---- scenario -------------------------------------------------------------
        if _has(
            low,
            r"\b(simulate|simulation|what if|scenario|reposition|rebalanc)\w*",
            r"\b(move|moving|moved|shift|shifting|relocat\w*|redistribut\w*|reallocat\w*|redeploy\w*)\b"
            r".*\b(vehicles?|cars?|taxis?|cabs?|fleet)\b",
            r"\b(vehicles?|cars?|taxis?|cabs?|fleet)\b.*\b(move|moving|moved|shift|shifting|"
            r"relocat\w*|redistribut\w*|reallocat\w*|redeploy\w*)\b",
        ):
            dates = find_dates(question, ctx)
            if dates:
                day = dates[0]
            elif ctx.eval_last is not None:
                day = ctx.eval_last
                assumptions.append(f"No date was given, so I used the last evaluation day, {day}.")
            else:
                return Plan(
                    "clarify",
                    clarification="Which date should I simulate? Scenarios use the evaluation days.",
                    assumptions=assumptions,
                )
            w = find_window(question)
            if w is None:
                w = (17, 20)
                assumptions.append("No time window was given, so I used 17:00 to 20:00.")
            args: dict[str, Any] = {"day": str(day), "start_hour": w[0], "end_hour": w[1]}
            m = re.search(r"(\d{2,3})\s*%\s*(service|served|of (the )?demand)", low)
            if m:
                args["min_service_share"] = min(1.0, int(m.group(1)) / 100)
            if zone_id is not None:
                up = re.search(r"(\d{1,3})\s*%\s*(more|higher|increase|extra|surge|above)", low)
                dn = re.search(r"(\d{1,3})\s*%\s*(less|lower|fewer|decrease|drop|below)", low)
                if up:
                    args["multipliers"] = {zone_id: 1 + int(up.group(1)) / 100}
                elif dn:
                    args["multipliers"] = {zone_id: max(0.0, 1 - int(dn.group(1)) / 100)}
            return Plan("scenario", [PlannedCall("run_rebalancing_scenario", args)], assumptions)
        # ---- anomalies ------------------------------------------------------------
        anomaly_words = _has(
            low,
            r"\banomal",
            r"\bunusual",
            r"\babnormal",
            r"\boutlier",
            r"\bunexpected",
            r"\bstrange",
            r"\bdeviat",
            r"\bspikes?\b",
            r"\bsurges?\b",
            r"\bdrops?\b",
            r"\bcollapse",
            r"\bodd\b",
            r"\bweird",
            r"\birregular",
            r"\batypical",
            r"\bout of the ordinary",
            r"\b(something|anything) (off|wrong)\b",
        )
        if _has(
            low,
            r"\b(why|what happened|reason|cause[ds]?|due to|responsible|behind)\b",
            r"\bexplain\w*\b",
        ) and (anomaly_words or find_dates(question, ctx)):
            c = clarify_zone()
            if c:
                return c
            args = {"rank": 1}
            if zone_id is not None:
                args["zone"] = zone_id
            dates = find_dates(question, ctx)
            if dates:
                args["day"] = str(dates[0])
            return Plan("explain_anomaly", [PlannedCall("explain_anomaly", args)], assumptions)
        if anomaly_words:
            c = clarify_zone()
            if c:
                return c
            args = {"limit": _top_n(low, 5)}
            if zone_id is not None:
                args["zone"] = zone_id
            if _has(low, r"\b(high|severe|major|serious)\b"):
                args["severity"] = "high"
            elif _has(low, r"\bmedium\b"):
                args["severity"] = "medium"
            if _has(low, r"\b(surge|spike|increase|above|jump)s?\b"):
                args["direction"] = "surge"
            elif _has(low, r"\b(drop|fall|decline|below|collapse|dip)s?\b"):
                args["direction"] = "drop"
            p = parse_period(question, ctx)
            if p is not None:
                s, e = _clip(p.start, p.end_exclusive, ctx)
                if s < e:
                    args["start"], args["end"] = str(s), str(e)
            return Plan("anomalies", [PlannedCall("get_anomalies", args)], assumptions)
        # ---- forecast -------------------------------------------------------------
        if _has(
            low,
            r"\bforecast",
            r"\bpredict",
            r"\btomorrow\b",
            r"\bnext day\b",
            r"\bexpect(ed)?\b.*\b(demand|pickups)\b",
            r"\bwill be\b",
        ):
            c = clarify_zone()
            if c:
                return c
            dates = find_dates(question, ctx)
            next_day = ctx.data_last + timedelta(days=1)
            years = {int(y) for y in re.findall(r"\b(20\d{2})\b", low)}
            beyond_dates = [d for d in dates if d > next_day]
            beyond_words = _has(
                low,
                r"\bnext (week|weekend|month|year|season|summer|winter|spring|fall|autumn)\b",
                r"\bnext (christmas|thanksgiving|halloween|easter|new year)\b",
                r"\bin (a|an|\d+|several|few) (days?|weeks?|months?|years?)\b",
                r"\b(this|next) (christmas|thanksgiving|summer|winter)\b",
            )
            if beyond_dates or beyond_words or (years and years != {ctx.data_last.year}):
                return Plan(
                    "clarify",
                    clarification=(
                        f"I can only forecast the day after the last day of data ({next_day}), or "
                        f"compare past forecasts with actuals for the evaluation days "
                        f"({ctx.eval_first} to {ctx.eval_last}). I cannot forecast further ahead."
                    ),
                    assumptions=assumptions,
                )
            args = {}
            if zone_id is not None:
                args["zone"] = zone_id
            if dates and _has(
                low,
                r"\bactual",
                r"\bvs\b",
                r"\bversus",
                r"\bcompared",
                r"\bhow close",
                r"\bwas it",
                r"\bhow well",
                r"\bpredicted\b",
            ):
                args.update(mode="backtest", day=str(dates[0]))
            else:
                args["mode"] = "next_day"
            return Plan("forecast", [PlannedCall("get_forecast", args)], assumptions)
        # ---- weather --------------------------------------------------------------
        if _has(
            low,
            r"\brain",
            r"\bsnow",
            r"\bfreez",
            r"\bweather\b",
            r"\bstorm",
            r"\bprecip",
            r"\bwet\b",
            r"\bdrizzl",
            r"\bdownpour",
            r"\bblizzard",
        ):
            if not _has(low, *_DEMAND_WORDS):
                return Plan(
                    "clarify",
                    clarification="I do not provide weather information. I can compare taxi demand on rainy, snowy or freezing days with other days; try asking how rain relates to demand.",
                    assumptions=assumptions,
                )
            c = clarify_zone()
            if c:
                return c
            p = period("all")
            cond = (
                "snow" if "snow" in low else "freezing" if _has(low, r"freez", r"cold") else "rain"
            )
            args = {"start": str(p.start), "end": str(p.end_exclusive), "condition": cond}
            if zone_id is not None:
                args["zone"] = zone_id
            return Plan("weather", [PlannedCall("get_weather_comparison", args)], assumptions)
        # ---- hourly profile -------------------------------------------------------
        if _has(
            low,
            r"\bpeak hour",
            r"\bbusiest hour",
            r"\bquietest hour",
            r"\brush hour\b.*\b(when|what)",
            r"\bhour of (the )?day",
            r"\bby hour\b",
            r"\bhourly\b",
            r"\bwhat time\b",
            r"\bwhen (is|are|do)\b.*\b(busy|busiest|demand|peak)",
        ):
            c = clarify_zone()
            if c:
                return c
            p = period("all")
            args = {"start": str(p.start), "end": str(p.end_exclusive)}
            if zone_id is not None:
                args["zone"] = zone_id
            return Plan("profile", [PlannedCall("get_hourly_profile", args)], assumptions)
        # ---- comparison -----------------------------------------------------------
        if _has(
            low,
            r"\bcompare",
            r"\bversus\b",
            r"\bvs\.?\b",
            r"\bcompared (to|with)\b",
            r"\bchange\b",
            r"\bgrow(th|n|ing)?\b",
            r"\bgrew\b",
            r"\bincrease[d]?\b",
            r"\bdecrease[d]?\b",
            r"\b(higher|lower|more|less|busier|quieter|bigger|smaller)\b.*\bthan\b",
            r"\bdifference between\b",
            r"\bup or down\b",
        ):
            c = clarify_zone()
            if c:
                return c
            sides = re.split(
                r"\b(?:versus|vs\.?|compared (?:to|with)|than|and|against|with)\b",
                question,
                maxsplit=1,
                flags=re.I,
            )
            pa = parse_period(sides[0], ctx, bare_month=True) if len(sides) == 2 else None
            pb = parse_period(sides[1], ctx, bare_month=True) if len(sides) == 2 else None
            args = {}
            if zone_id is not None:
                args["zone"] = zone_id
            metric = (
                "revenue"
                if _has(low, r"revenue|fare")
                else "dropoffs"
                if "dropoff" in low
                else "pickups"
            )
            args["metric"] = metric
            if pa and pb:
                a0, a1 = _clip(pa.start, pa.end_exclusive, ctx)
                b0, b1 = _clip(pb.start, pb.end_exclusive, ctx)
                if a0 < a1 and b0 < b1:
                    args.update(a_start=str(a0), a_end=str(a1), b_start=str(b0), b_end=str(b1))
                    return Plan("compare", [PlannedCall("compare_periods", args)], assumptions)
            p = parse_period(question, ctx)
            if p is None:
                p = period("last7")
            s, e = _clip(p.start, p.end_exclusive, ctx)
            length = (e - s).days
            a0 = s - timedelta(days=length)
            if a0 < ctx.data_first:
                return Plan(
                    "clarify",
                    clarification="I need two periods to compare (for example 'last week vs the week before'), and there is not enough earlier data for that one.",
                    assumptions=assumptions,
                )
            assumptions.append(
                f"One period was given ({s} to {e - timedelta(days=1)}), so I compared it with the {length} days before it."
            )
            args.update(a_start=str(a0), a_end=str(s), b_start=str(s), b_end=str(e))
            return Plan("compare", [PlannedCall("compare_periods", args)], assumptions)
        # ---- rankings -------------------------------------------------------------
        if _has(
            low,
            r"\bbusiest\b",
            r"\b(biggest|largest|most popular)\b.*\b(zones?|areas?|neighbou?rhoods?|spots?)\b",
            r"\btop\b",
            r"\bmost (popular|pickups|demand|active|trips)",
            r"\bhighest\b",
            r"\bquietest\b",
            r"\bleast\b",
            r"\blowest\b",
            r"\brank(ing|ed)?\b",
            r"\bwhich (zones|areas|neighbou?rhoods)\b",
            r"\bwhere .*(most|demand)",
        ):
            p = period("last7")
            args = {"start": str(p.start), "end": str(p.end_exclusive), "limit": _top_n(low, 5)}
            if _has(low, r"quietest", r"\bleast\b", r"\blowest\b"):
                args["ascending"] = True
            if _has(low, r"revenue|fare"):
                args["metric"] = "revenue"
            elif "dropoff" in low:
                args["metric"] = "dropoffs"
            return Plan("top_zones", [PlannedCall("get_top_zones", args)], assumptions)
        # ---- one zone -------------------------------------------------------------
        if zone_named and _has(
            low,
            r"\bpickups?\b",
            r"\bdemand\b",
            r"\btrips?\b",
            r"\bbusy\b",
            r"\bhow (many|much)\b",
            r"\bstats\b",
            r"\bnumbers?\b",
            r"\btell me about\b",
            r"\bsummary\b",
        ):
            c = clarify_zone()
            if c:
                return c
            p = period("last7")
            return Plan(
                "zone_metrics",
                [
                    PlannedCall(
                        "get_zone_metrics",
                        {"zone": zone_id, "start": str(p.start), "end": str(p.end_exclusive)},
                    )
                ],
                assumptions,
            )
        if _has(
            low,
            r"\btotal (pickups|trips|demand)\b",
            r"\bhow many (pickups|trips)\b",
            r"\bcitywide\b|\bcity-wide\b|\bwhole city\b|\bnyc\b",
        ):
            p = period("last7")
            e = p.end_exclusive
            s = p.start
            if (e - s).days < 1:
                s = e - timedelta(days=1)
            # citywide total: compare against the equal earlier period is not asked; use the comparison tool with A=B trick is wrong,
            # so report through the ranking's shares: use compare with the previous period instead.
            length = (e - s).days
            a0 = s - timedelta(days=length)
            if a0 >= ctx.data_first:
                assumptions.append(
                    f"For a citywide total I also fetched the {length} days before it for context."
                )
                return Plan(
                    "compare",
                    [
                        PlannedCall(
                            "compare_periods",
                            {
                                "a_start": str(a0),
                                "a_end": str(s),
                                "b_start": str(s),
                                "b_end": str(e),
                            },
                        )
                    ],
                    assumptions,
                )
        return Plan(
            "clarify",
            clarification=(
                "I could not tell what to look up. I can answer questions about: busiest zones, a zone's "
                "demand, comparisons between periods, hourly patterns, weather association, next-day forecasts "
                "and forecast accuracy, anomalies and why they may have happened, simulated repositioning "
                "scenarios, and what a term means."
            ),
            assumptions=assumptions,
        )
