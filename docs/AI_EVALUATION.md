# AI analyst: design and evaluation

STATUS: deterministic mode **VERIFIED as measured below**. LLM mode **UNVERIFIED**: no LLM API key
was available, so it has only been tested against a mocked HTTP transport and has never been run
against the real service. No LLM-mode quality claim is made anywhere in this project.

## What the analyst is

A question-answering layer over the project's own results. It does not browse, does not write to
anything, and cannot run SQL or code. Its pipeline (ADR-012):

1. **Screen** the question: refuse requests to modify data, run code or SQL, reveal secrets or
   instructions, ask about other services, or extract personal information. Instruction-override
   phrasing ("ignore previous instructions") is flagged and ignored.
2. **Plan**: a rule-based planner (or an LLM, if configured) selects among **13 read-only tools**
   and their arguments. Ambiguity produces a clarification question; every default the planner
   applies (for example "no period given: last 7 days") is stated as an ASSUMPTION.
3. **Run the tools.** Arguments are validated and bounded; tools return named *facts*.
4. **Compose** the answer from facts. Every sentence is labelled FACT, INTERPRETATION, ASSUMPTION or
   LIMITATION and cites the facts it uses. Nothing is free text from a model.
5. **Verify grounding.** Any FACT or INTERPRETATION sentence containing a number or date that is not
   in the facts it cites is withheld and replaced by a notice.
6. **Show its work**: the response lists the tools used, their arguments and the facts returned.
   There is no hidden reasoning to expose.

The planner never sees tool outputs, so data (zone names, event text) cannot inject instructions.
The LLM planner, if enabled, can only choose tools; it cannot write numbers.

## How it was evaluated

Ground truth comes from **independent code**: raw SQL against the database and the stored
evaluation and anomaly artifacts, never the analyst's own tools. Each question is scored on up to
nine checks (status, tools, numbers, grounding, required phrases, forbidden phrases, assumption
disclosure, no tools for refused questions, no causal wording). A question passes only if every
applicable check passes. A test deliberately corrupts a tool and confirms the benchmark fails, so
the benchmark can fail.

Two question sets, both written by the system's author:

* **Development set** (80 questions, 13 categories: rankings, zones, comparisons, patterns,
  forecast, anomalies, optimisation, definitions, unsafe requests, prompt injection, out-of-scope,
  causal traps, range traps). Frozen before its first run.
* **Held-out set** (40 fresh questions with new phrasings), written *after* the planner had been
  tuned on the development set, **run once, and not tuned to**.

## Results (real data)

| Run | Passed | Rate | Note |
|---|---:|---:|---|
| Development, first run | 72 / 80 | 90.0% | before any fix |
| Development, after general fixes | 80 / 80 | 100.0% | fixes were made against this set, so this is optimistic |
| **Held-out, single run** | **31 / 40** | **77.5%** | the fairer estimate of unseen-question performance |

Safety-related checks on the held-out run: grounding 30 / 30, no causal wording 30 / 30, forbidden
text absent 3 / 3, every unsafe or injection request refused (safety 4 / 4, injection 2 / 2), no tool
run for any question that should not run one, except two where it answered instead of asking (below).
Median latency 25 ms, p95 49 ms.

Held-out failures (9), by how they fail the user:

| Kind | Count | Examples |
|---|---:|---|
| Chose the wrong tool (misleading) | 4 | asked about forecast *error*, got a next-day forecast; asked what *explains* the biggest deviation, got a list of anomalies |
| Unhelpful: asked when it could have answered | 3 | "Do wet days have more or fewer pickups?" (vocabulary it does not know), "Anything odd happening in Penn Station?" |
| Answered something that should have been declined or clarified (misleading) | 2 | an unknown place ("Gotham City") got an answer instead of a question; "next Christmas" was treated as next-day |

**These are the important findings.** Language coverage is the rule planner's weakness: it
recognises the intents and phrasings it encodes, and unfamiliar wording either fails to match
(unhelpful but honest) or matches the wrong intent (misleading). What did *not* fail, on any run, is
what the architecture guarantees: numbers are traceable to tool facts, unsafe requests are refused,
and no answer asserts a cause.

## Bugs the benchmark found in the analyst

Real defects, all fixed with general changes and covered by tests: comparing two bare month names,
"biggest/largest" wrongly implying a severity filter, "higher ... than" comparisons, "cause"
questions treated as weather-only, personal-information phrasing in reverse order, an unsupported
forecast year answered as next-day, a silent fallback to all data when a requested period had none,
borough questions answered citywide, and tools crashing on a stale artifact (now reported cleanly).
Separately, five stray control characters introduced by a scripted edit had silently broken several
regular expressions; the benchmark exposed it.

## What this evaluation does not show

* The questions were written by the same person who built the system. A different author would
  phrase things differently; expect lower scores.
* Only one dataset (January to May 2024, yellow taxis) and one language (English).
* The held-out set is small (40), so its 77.5% has wide uncertainty.
* It says nothing about LLM mode. Reproducing this evaluation with an LLM planner requires a key and
  is listed as future work; until then LLM mode is **UNVERIFIED**.
* "Numbers correct" means the numbers match independent SQL for the *intent the analyst chose*; a
  correct number for the wrong intent is caught only by the tools check.

## Reproduce

```bash
export MOBILITYOPS_MODE=real
python -m mobilityops.cli analyst-benchmark --label first-run            # development set
python -m mobilityops.cli analyst-benchmark --holdout --label holdout    # held-out set
python -m mobilityops.cli analyst-benchmark-report --out reports/ai_evaluation_real.md
```

Runs are appended to `artifacts/<mode>/analyst/benchmark.json`; the first result is never
overwritten. The raw runs used here are committed in `reports/ai_benchmark_real.json`.
