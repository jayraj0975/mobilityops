"""The analyst: screen -> plan -> run read-only tools -> compose -> verify grounding.

The response always shows what was done: the tools called with their arguments and the facts they
returned, plus every statement labelled FACT / INTERPRETATION / ASSUMPTION / LIMITATION. It does not
expose model reasoning; there is nothing to expose beyond the tool trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal

import numpy as np
import pandas as pd

from mobilityops.analyst.answer import Statement, compose
from mobilityops.analyst.guard import sanitize, screen, ungrounded_numbers
from mobilityops.analyst.llm import LLMUnavailable
from mobilityops.analyst.planner import Plan, Planner, PlanningContext, RulePlanner
from mobilityops.analyst.tools import TOOLS, ToolResult, call_tool
from mobilityops.api.services import NotReady, Services
from mobilityops.log import get_logger

log = get_logger("analyst")

MAX_CALLS = 4
MAX_TRACE_ROWS = 25
Status = Literal["answered", "partial", "clarify", "refused", "no_data"]


@dataclass
class ToolTrace:
    call_id: str
    name: str
    args: dict[str, Any]
    ok: bool
    error: str | None
    facts: list[dict[str, str]]
    data: dict[str, Any]


@dataclass
class AnalystAnswer:
    question: str
    status: Status
    mode: str  # planner used: "deterministic" or "llm"
    statements: list[Statement]
    tools_used: list[ToolTrace] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    grounding: dict[str, int] = field(default_factory=lambda: {"checked": 0, "removed": 0})
    intent: str = ""
    data_label: str = ""


def jsonable(x: Any, depth: int = 0) -> Any:
    """Make tool data JSON-safe and bounded for the trace."""
    if depth > 6:
        return "..."
    if isinstance(x, dict):
        return {str(k): jsonable(v, depth + 1) for k, v in list(x.items())[:60]}
    if isinstance(x, (list, tuple)):
        return [jsonable(v, depth + 1) for v in list(x)[:MAX_TRACE_ROWS]]
    if isinstance(x, np.ndarray):
        return [jsonable(v, depth + 1) for v in x.tolist()[:MAX_TRACE_ROWS]]
    if isinstance(x, (np.generic,)):
        return jsonable(x.item(), depth)
    if isinstance(x, float) and np.isnan(x):
        return None
    if isinstance(x, (pd.Timestamp,)):
        return x.isoformat()
    if isinstance(x, str):
        return x[:400]
    if x is None or isinstance(x, (bool, int, float)):
        return x
    return str(x)[:400]


class Analyst:
    def __init__(self, services: Services, planner: Planner | None = None) -> None:
        self.services = services
        self.planner: Planner = planner or RulePlanner()
        self._fallback = RulePlanner()

    # ------------------------------------------------------------------------ context
    def _context(self) -> PlanningContext:
        an = self.services.analytics()
        rng = an.data_range()
        first, last = rng.start.date(), (rng.end - timedelta(days=1)).date()
        eval_first = eval_last = None
        try:
            preds = self.services.predictions()
            t = self.services.tensor()
            eval_first = t.days[int(preds["day_index"].min())].date()
            eval_last = t.days[int(preds["day_index"].max())].date()
        except NotReady:
            pass
        return PlanningContext(first, last, an.zones(), eval_first, eval_last)

    # ---------------------------------------------------------------------------- ask
    def ask(self, question: str) -> AnalystAnswer:
        q = sanitize(question)
        label = self.services.data_label
        if not q:
            return AnalystAnswer(
                question, "clarify", self.planner.name,
                [Statement("LIMITATION", "Please ask a question about the taxi-demand data.")],
                data_label=label,
            )  # fmt: skip
        s = screen(q)
        warnings = list(s.flags) if s.injection_suspected else []
        if s.refused:
            log.info("refused", extra={"ctx": {"flags": s.flags}})
            return AnalystAnswer(
                q, "refused", "deterministic",
                [Statement("LIMITATION", s.reason or "I cannot help with that request.")],
                warnings=warnings, data_label=label, intent="refused",
            )  # fmt: skip
        try:
            ctx = self._context()
        except NotReady as exc:
            return AnalystAnswer(
                q, "no_data", self.planner.name,
                [Statement("LIMITATION", f"The data is not ready: {exc}.")],
                data_label=label,
            )  # fmt: skip
        mode = self.planner.name
        try:
            plan: Plan = self.planner.plan(q, ctx)
        except LLMUnavailable as exc:
            warnings.append(f"{exc}; used the deterministic planner instead")
            mode = "deterministic (LLM unavailable)"
            plan = self._fallback.plan(q, ctx)
        if plan.clarification:
            return AnalystAnswer(
                q, "clarify", mode,
                [*(Statement("ASSUMPTION", a) for a in plan.assumptions),
                 Statement("LIMITATION", plan.clarification)],
                warnings=warnings, data_label=label, intent=plan.intent,
            )  # fmt: skip
        results = [
            call_tool(self.services, f"c{i}", pc.name, pc.args)
            for i, pc in enumerate(plan.calls[:MAX_CALLS], start=1)
        ]
        statements = compose(results, plan.assumptions)
        statements, checked, removed = self._verify(statements, results)
        ok = [r for r in results if r.ok]
        if not ok:
            status: Status = "no_data"
        elif len(ok) < len(results) or removed:
            status = "partial"
        else:
            status = "answered"
        log.info(
            "answered",
            extra={"ctx": {"intent": plan.intent, "tools": [r.name for r in results],
                           "status": status, "removed": removed}},
        )  # fmt: skip
        return AnalystAnswer(
            q, status, mode, statements,
            tools_used=[self._trace(r) for r in results],
            warnings=warnings, grounding={"checked": checked, "removed": removed},
            intent=plan.intent, data_label=label,
        )  # fmt: skip

    # ------------------------------------------------------------------------ grounding
    @staticmethod
    def _verify(
        statements: list[Statement], results: list[ToolResult]
    ) -> tuple[list[Statement], int, int]:
        """Replace FACT/INTERPRETATION statements whose numbers are not in the facts they cite."""
        by_id = {fid: f for r in results for fid, f in r.facts.items()}
        arg_text = {
            r.call_id: [str(v) for v in r.args.values()] + [str(v) for v in _flat(r.args)]
            for r in results
        }
        out: list[Statement] = []
        checked = removed = 0
        for st in statements:
            if st.kind not in ("FACT", "INTERPRETATION"):
                out.append(st)
                continue
            checked += 1
            allowed = [by_id[i].display for i in st.fact_ids if i in by_id]
            for i in st.fact_ids:
                allowed.extend(arg_text.get(i.split(".")[0], []))
            bad = ungrounded_numbers(st.text, allowed)
            if bad:
                removed += 1
                out.append(
                    Statement(
                        "LIMITATION",
                        "A statement was withheld because it contained a figure "
                        "that could not be traced to a tool result.",
                    )
                )
            else:
                out.append(st)
        return out, checked, removed

    @staticmethod
    def _trace(r: ToolResult) -> ToolTrace:
        return ToolTrace(
            call_id=r.call_id,
            name=r.name,
            args=jsonable(r.args),
            ok=r.ok,
            error=r.error,
            facts=[{"id": f.id, "label": f.label, "value": f.display} for f in r.facts.values()],
            data=jsonable(r.data),
        )


def _flat(d: dict[str, Any]) -> list[Any]:
    out: list[Any] = []
    for v in d.values():
        if isinstance(v, dict):
            out.extend(_flat(v))
            out.extend(str(k) for k in v)
        else:
            out.append(v)
    return out


def tool_catalog() -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "arguments": t.args.model_json_schema()}
        for t in TOOLS.values()
    ]
