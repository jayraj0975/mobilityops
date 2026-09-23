"""Render the analyst benchmark history as Markdown (numbers generated from stored runs)."""

from __future__ import annotations

from typing import Any


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def failure_kind(r: dict[str, Any]) -> str:
    """Classify a failed question by how it fails the user."""
    exp, got = r["expected_status"], r["status"]
    if exp in ("refused", "clarify") and got in ("answered", "partial"):
        return "answered a question that should have been declined or clarified (misleading)"
    if exp == "refused" and got != "refused":
        return "unsafe request not refused"
    if exp == "answered" and got in ("clarify", "refused"):
        return "unhelpful: asked or refused when it could have answered"
    if not r["checks"].get("tools", True):
        return "chose the wrong tool (misleading)"
    if not r["checks"].get("numbers", True):
        return "wrong or missing numbers (misleading)"
    return "other check failed"


def _find(history: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    return next((h for h in history if h["label"] == label), None)


def render(history: list[dict[str, Any]]) -> str:
    dev_first = _find(history, "first-run")
    dev_runs = [
        h
        for h in history
        if h.get("question_set", "analyst_questions.json") == "analyst_questions.json"
    ]
    dev_last = dev_runs[-1] if dev_runs else None
    holdout = _find(history, "holdout-first-run")
    head = history[-1]
    lines = [
        f"# AI analyst evaluation ({head['data_label']})",
        "",
        f"_Generated from `artifacts/{head['mode']}/analyst/benchmark.json` by "
        "`python -m mobilityops.cli analyst-benchmark-report`; do not edit._",
        "",
        "STATUS: deterministic mode VERIFIED as measured below. **LLM mode: UNVERIFIED** (no LLM key "
        "was available; it was never benchmarked and no LLM result is claimed).",
        "",
        "## Headline",
        "",
        "| Question set | Questions | Passed | Rate | Notes |",
        "|---|---:|---:|---:|---|",
    ]
    if dev_first:
        lines.append(
            f"| Development set, first run | {dev_first['questions']} | {dev_first['passed']} | "
            f"{_pct(dev_first['pass_rate'])} | before any fixes |"
        )
    if dev_last and dev_last is not dev_first:
        lines.append(
            f"| Development set, after fixes | {dev_last['questions']} | {dev_last['passed']} | "
            f"{_pct(dev_last['pass_rate'])} | planner was fixed after seeing failures on this set, "
            "so this rate is optimistic |"
        )
    if holdout:
        lines.append(
            f"| **Held-out set, single run** | {holdout['questions']} | {holdout['passed']} | "
            f"**{_pct(holdout['pass_rate'])}** | written after tuning, run once, not tuned to; "
            "the fairer estimate |"
        )
    lines += [
        "",
        "Every question is scored on several checks against **independent ground truth** (raw SQL on "
        "the database and the stored evaluation and anomaly artifacts, not the analyst's own tools). "
        "A question passes only if every applicable check passes.",
        "",
        "| Check | Meaning |",
        "|---|---|",
        "| status | answered / clarify / refused as expected |",
        "| tools | exactly the expected tools ran |",
        "| numbers | every ground-truth value appears in the answer's FACT statements |",
        "| grounding | no statement was withheld for an untraceable number |",
        "| statements | required phrases present (for example the simulation label) |",
        "| forbidden | forbidden phrases absent (causal wording, secrets) |",
        "| assumption | a missing period is disclosed as an assumption |",
        "| no_tools | refused or clarified questions ran no tool |",
        "| non_causal | no answer statement claims a cause |",
        "",
    ]
    for title, run in (("Development set (final run)", dev_last), ("Held-out set", holdout)):
        if not run:
            continue
        lines += [
            f"## {title}",
            "",
            f"{run['passed']}/{run['questions']} passed. Median latency "
            f"{run['latency_ms']['median']:.0f} ms, p95 {run['latency_ms']['p95']:.0f} ms.",
            "",
            "| Check | Passed | Applicable |",
            "|---|---:|---:|",
            *[f"| {c} | {v['passed']} | {v['applicable']} |" for c, v in run["per_check"].items()],
            "",
            "| Category | Passed | Questions |",
            "|---|---:|---:|",
            *[
                f"| {c} | {v['passed']} | {v['questions']} |"
                for c, v in sorted(run["per_category"].items())
            ],
            "",
            f"Safety: {run['safety']['refused_correctly']} of {run['safety']['should_refuse']} unsafe "
            f"or out-of-scope requests refused; {run['safety']['legitimate_refused']} of "
            f"{run['safety']['legitimate_questions']} legitimate questions wrongly refused.",
            "",
        ]
    for title, run in (
        ("Failures on the development set's first run", dev_first),
        ("Failures on the held-out set", holdout),
    ):
        if not run:
            continue
        bad = [r for r in run["results"] if not r["passed"]]
        lines += [f"## {title}", ""]
        if not bad:
            lines += ["None.", ""]
            continue
        kinds: dict[str, int] = {}
        for r in bad:
            kinds[failure_kind(r)] = kinds.get(failure_kind(r), 0) + 1
        lines += [
            "| Kind of failure | Count |",
            "|---|---:|",
            *[f"| {k} | {v} |" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])],
            "",
            "| ID | Question | Got | Why it failed |",
            "|---|---|---|---|",
            *[
                f"| {r['id']} | {r['question'].replace('|', '/')} | {r['status']}"
                f"{' via ' + ', '.join(r['tools']) if r['tools'] else ''} | "
                f"{'; '.join(r['reasons']).replace('|', '/')} |"
                for r in bad
            ],
            "",
        ]
    lines += [
        "## Run history",
        "",
        "| Label | Question set | Passed | Rate |",
        "|---|---|---:|---:|",
        *[
            f"| {h['label']} | {h.get('question_set', '')} | {h['passed']}/{h['questions']} | "
            f"{_pct(h['pass_rate'])} |"
            for h in history
        ],
        "",
        "## What this does and does not show",
        "",
        "* The questions were written by the system's author; a different author would phrase things "
        "differently. The held-out set is smaller and also author-written.",
        "* The rule planner covers the intents it encodes. Unseen phrasing, unusual place names and "
        "far-future dates are its weak spots (see the held-out failures).",
        "* Grounding, refusal and non-causal wording held at 100% on every run, by construction: "
        "answers are assembled from tool facts and checked, and the checks are deterministic.",
        "* The held-out run was executed before two later planner changes (borough questions ask for "
        "a zone; tools report malformed artifacts cleanly). Neither touches a held-out question, and "
        "the held-out result was not re-run or tuned to.",
        "* Only one dataset (Jan-May 2024, yellow taxis) was used.",
        "* LLM planner mode was **not** evaluated (UNVERIFIED).",
        "",
    ]
    return "\n".join(lines)
