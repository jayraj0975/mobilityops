"""Compose labelled answer statements from tool facts.

Every sentence is built from a tool's *facts* (never from free text) and records which facts it
used. Kinds:

* FACT: a value a tool returned, or a plain restatement of one.
* INTERPRETATION: what the facts suggest, hedged; never asserts a cause.
* ASSUMPTION: a default the analyst applied, or an assumption a simulation rests on.
* LIMITATION: a caveat the reader needs (data coverage, accuracy status, simulated results).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from mobilityops.analyst.tools import ToolResult

Kind = Literal["FACT", "INTERPRETATION", "ASSUMPTION", "LIMITATION"]
ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth",
            "tenth")  # fmt: skip


def ordinal(i: int) -> str:
    """Words, not digits: a list position is a label, not a figure the tools returned."""
    return ORDINALS[i - 1] if 1 <= i <= len(ORDINALS) else f"next (#{i})"


@dataclass(frozen=True)
class Statement:
    kind: Kind
    text: str
    fact_ids: tuple[str, ...] = ()


@dataclass
class Cite:
    """Reads facts by short key and remembers which were used."""

    r: ToolResult
    used: list[str] = field(default_factory=list)

    def __call__(self, key: str) -> str:
        fid = f"{self.r.call_id}.{key}"
        self.used.append(fid)
        return self.r.facts[fid].display

    def has(self, key: str) -> bool:
        return f"{self.r.call_id}.{key}" in self.r.facts

    def value(self, key: str) -> float | str | None:
        fid = f"{self.r.call_id}.{key}"
        self.used.append(fid)
        return self.r.facts[fid].value

    def stmt(self, kind: Kind, text: str) -> Statement:
        return Statement(kind, text, tuple(dict.fromkeys(self.used)))


def _overview(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    return [
        c.stmt(
            "FACT",
            f"The loaded data is {c('label')}: {c('trips')} valid taxi trips across {c('zones')} "
            f"zones, from {c('start')} to {c('end')}.",
        )
    ]


def _zone(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    out = [
        c.stmt(
            "FACT",
            f"{c('zone')} had {c('total')} pickups over {c('period')} "
            f"({c('days')} days, about {c('per_day')} a day); its busiest day was {c('peak_day')} "
            f"with {c('peak_day_value')}.",
        )
    ]
    c2 = Cite(r)
    if c2.has("rank"):
        out.append(
            c2.stmt(
                "FACT",
                f"It ranked number {c2('rank')} among all zones for pickups, with {c2('share')} of "
                "all pickups in the period.",
            )
        )
    if c2.has("cv"):
        out.append(
            c2.stmt(
                "FACT", f"Its daily pickups varied by about {c2('cv')} of their mean (std / mean)."
            )
        )
    return out


def _top(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    lines = []
    i = 1
    while c.has(f"r{i}.zone"):
        lines.append(
            f"{ordinal(i)}, {c(f'r{i}.zone')}: {c(f'r{i}.value')} "
            f"({c(f'r{i}.share')} of the city total)"
        )
        i += 1
    order = "quietest" if r.args.get("ascending") else "busiest"
    return [
        c.stmt(
            "FACT",
            f"The {order} zones by {r.args['metric']} over {c('period')} were: "
            + "; ".join(lines)
            + ".",
        )
    ]


def _compare(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    a = r.args
    out = [
        c.stmt(
            "FACT",
            f"For {c('scope')}, {a['metric']} were {c('a_total')} in period A ({c('a_period')}, "
            f"{c('a_days')} days) and {c('b_total')} in period B ({c('b_period')}, "
            f"{c('b_days')} days): {c('a_per_day')} versus {c('b_per_day')} per day.",
        )
    ]
    if c.has("change_pct"):
        v = c.value("change_pct")
        direction = "higher" if isinstance(v, float) and v > 0 else "lower"
        out.append(
            c.stmt(
                "FACT",
                f"The per-day level changed by {c('change_pct')} from period A to period B.",
            )
        )
        out.append(
            Statement(
                "INTERPRETATION",
                f"Per-day demand was {direction} in period B than in period A. This compares two "
                "periods; it does not explain the difference.",
                (c.used and (c.used[-1],)) or (),
            )
        )
    return out


def _profile(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    return [
        c.stmt(
            "FACT",
            f"For {c('scope')}, the busiest hour of the day was {c('peak_hour')} "
            f"(about {c('peak_avg')} pickups on average) and the quietest was {c('low_hour')} "
            f"(about {c('low_avg')}).",
        )
    ]


def _weather(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    out = [
        c.stmt(
            "FACT",
            f"There were {c('days_with')} days with {c('condition')} and "
            f"{c('days_without')} without.",
        )
    ]
    if c.has("with"):
        c2 = Cite(r)
        text = (
            f"Mean daily pickups were {c2('with')} on "
            f"{r.facts[r.call_id + '.condition'].display} days "
            f"and {c2('without')} on other days"
        )
        if c2.has("ratio"):
            text += f" (ratio {c2('ratio')}"
            if c2.has("adj_ratio"):
                text += f"; {c2('adj_ratio')} after adjusting for the weekday mix"
            text += ")"
        out.append(c2.stmt("FACT", text + "."))
        out.append(
            Statement(
                "INTERPRETATION",
                "This is an association between weather and demand on the days observed; other "
                "differences between those days are not controlled for.",
            )
        )
    return out


def _forecast(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    if r.args.get("mode") == "backtest":
        out = [
            c.stmt(
                "FACT",
                f"For {c('scope')} on {c('date')}, actual pickups were {c('actual')} and the "
                f"out-of-sample forecast was {c('forecast')}.",
            )
        ]
        c2 = Cite(r)
        if c2.has("wape"):
            out.append(
                c2.stmt(
                    "FACT",
                    f"The hourly forecasts had an error (WAPE) of {c2('wape')} that day, and "
                    f"{c2('inside')} of hours fell inside the {c2('nominal')} interval.",
                )
            )
        return out
    out = [
        c.stmt(
            "FACT",
            f"The forecast for {c('date')} ({c('scope')}) is about {c('total')} pickups, with the "
            f"busiest hour around {c('peak_hour')} (about {c('peak_value')}).",
        )
    ]
    if c.has("peak_lo"):
        c2 = Cite(r)
        out.append(
            c2.stmt(
                "FACT",
                f"For that hour the {c2('nominal')} interval runs from {c2('peak_lo')} to "
                f"{c2('peak_hi')}.",
            )
        )
    if c.has("coverage"):
        c3 = Cite(r)
        out.append(
            c3.stmt(
                "FACT",
                f"On held-out days these {c3('nominal')} intervals actually contained "
                f"{c3('coverage')} of values.",
            )
        )
    return out


def _performance(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    out = [
        c.stmt(
            "FACT",
            f"On {c('test_days')} held-out days ({c('test_rows')} zone-hours), the forecasting "
            f"model's error (WAPE) was {c('wape')} against {c('baseline_wape')} for the strongest "
            f"baseline ({c('best_baseline')}) and {c('naive_wape')} for copying yesterday.",
        )
    ]
    c2 = Cite(r)
    out.append(
        c2.stmt(
            "FACT",
            f"That is a difference of {c2('gain_pp')} percentage points against the strongest "
            f"baseline ({c2('ci_level')} interval {c2('gain_lo')} to {c2('gain_hi')}); "
            f"the {c2('nominal')} intervals cover {c2('coverage')} of held-out values.",
        )
    )
    lo = r.facts[f"{r.call_id}.gain_lo"].value
    small = isinstance(lo, float) and lo > 0
    out.append(
        Statement(
            "INTERPRETATION",
            "The improvement over the strongest baseline is modest"
            + (" but its interval excludes zero." if small else " and its interval includes zero."),
            (f"{r.call_id}.gain_lo", f"{r.call_id}.gain_pp"),
        )
    )
    return out


def _anomalies(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    out = [
        c.stmt(
            "FACT",
            f"{c('total')} anomaly events match ({c('filters')}), among days scored "
            f"{c('scored_days')}.",
        )
    ]
    i = 1
    while c.has(f"e{i}.zone"):
        c2 = Cite(r)
        line = (
            f"The {ordinal(i)} event: {c2(f'e{i}.zone')}, {c2(f'e{i}.when')}, a {c2(f'e{i}.dir')} "
            f"of {c2(f'e{i}.sev')} severity"
        )
        if c2.has(f"e{i}.ratio"):
            line += f", {c2(f'e{i}.ratio')}x the forecast"
        out.append(c2.stmt("FACT", line + "."))
        i += 1
    return out


def _explain(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    out = [
        c.stmt(
            "FACT",
            f"{c('zone')}, {c('when')}: a {c('direction')} with {c('actual')} pickups against a "
            f"forecast of {c('forecast')} (event score {c('score')}).",
        )
    ]
    c2 = Cite(r)
    ctx = []
    i = 0
    while c2.has(f"ctx{i}"):
        ctx.append(c2(f"ctx{i}"))
        i += 1
    ctx.append(f"{c2('overlap')} other zones had events in the same direction at the same time")
    out.append(c2.stmt("FACT", "The following coincided with it: " + "; ".join(ctx) + "."))
    out.append(
        Statement(
            "INTERPRETATION",
            "These are things that happened at the same time. The data does not show that any of "
            "them caused the deviation.",
        )
    )
    return out


def _scenario(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    if c.has("after"):
        out = [
            c.stmt(
                "FACT",
                f"For {c('window')}, the simulated served share rises from {c('before')} to "
                f"{c('after')} by repositioning {c('moved')} of {c('fleet')} vehicles "
                f"({c('km')} km driven empty).",
            )
        ]
    else:
        out = [
            c.stmt(
                "FACT",
                f"For {c('window')}, the solver status is {c('status')}. {c('message')}. "
                f"Without repositioning the served share is {c('before')}.",
            )
        ]
        if c.has("best"):
            out.append(c.stmt("FACT", f"The best attainable served share is {c('best')}."))
    keys = [k for k in r.facts if ".assume." in k]
    if keys:
        parts = [f"{k.split('.assume.')[1].replace('_', ' ')} = {r.facts[k].display}" for k in keys]
        out.append(
            Statement(
                "ASSUMPTION", "The simulation assumes: " + "; ".join(parts) + ".", tuple(keys)
            )
        )
    return out


def _optimization(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    out = [
        c.stmt(
            "FACT",
            f"Over {c('windows')} simulated day-windows, the served share was {c('none')} with no "
            f"repositioning, {c('lgbm')} planning with the LightGBM forecast, {c('seasonal')} "
            f"planning with the seasonal-mean forecast, and {c('oracle')} planning with the actual "
            f"demand (an unattainable upper bound); the LightGBM plan added {c('gain_pp')} "
            "percentage points.",
        )
    ]
    lg = r.facts[f"{r.call_id}.lgbm"].value
    se = r.facts[f"{r.call_id}.seasonal"].value
    if isinstance(lg, float) and isinstance(se, float) and se > lg:
        out.append(
            Statement(
                "INTERPRETATION",
                "Planning with the simple seasonal-mean forecast did slightly better than planning "
                "with the LightGBM forecast, so the lower forecast error did not carry over "
                "to this decision.",
                (f"{r.call_id}.lgbm", f"{r.call_id}.seasonal"),
            )
        )
    return out


def _glossary(r: ToolResult) -> list[Statement]:
    c = Cite(r)
    return [c.stmt("FACT", f"{c('term')}: {c('definition')}")]


COMPOSERS: dict[str, Callable[[ToolResult], list[Statement]]] = {
    "get_data_overview": _overview,
    "get_zone_metrics": _zone,
    "get_top_zones": _top,
    "compare_periods": _compare,
    "get_hourly_profile": _profile,
    "get_weather_comparison": _weather,
    "get_forecast": _forecast,
    "get_model_performance": _performance,
    "get_anomalies": _anomalies,
    "explain_anomaly": _explain,
    "run_rebalancing_scenario": _scenario,
    "get_optimization_findings": _optimization,
    "get_glossary": _glossary,
}


def compose(results: list[ToolResult], assumptions: list[str]) -> list[Statement]:
    out: list[Statement] = [Statement("ASSUMPTION", a) for a in assumptions]
    notes: list[str] = []
    for r in results:
        if not r.ok:
            out.append(Statement("LIMITATION", f"I could not complete '{r.name}': {r.error}."))
            continue
        out.extend(COMPOSERS[r.name](r))
        notes.extend(x for x in r.notes if x not in notes)
    out.extend(Statement("LIMITATION", note) for note in notes)
    return out
