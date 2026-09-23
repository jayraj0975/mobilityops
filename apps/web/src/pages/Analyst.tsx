import { useEffect, useRef, useState } from "react";
import { ApiError, api, type Schemas } from "../api/client";
import { ErrorState } from "../components/State";
import { useAsync } from "../lib/useAsync";

const EXAMPLES = [
  "What were the busiest zones last week?",
  "How accurate is the forecast?",
  "Compare last week with the week before",
  "Were there any high severity anomalies?",
  "What does WAPE mean?",
];

const KIND_LABEL: Record<string, string> = {
  FACT: "Fact",
  INTERPRETATION: "Interpretation",
  ASSUMPTION: "Assumption",
  LIMITATION: "Limitation",
};

function Answer({ a }: { a: Schemas["AnalystResponse"] }) {
  return (
    <article className={`answer answer-${a.status}`} aria-label={`Answer to: ${a.question}`}>
      <p className="muted small">
        Status: <strong>{a.status}</strong> · planner: {a.mode} · {a.data_label}
        {(a.grounding.checked ?? 0) > 0 &&
          ` · grounding: ${(a.grounding.checked ?? 0) - (a.grounding.removed ?? 0)} of ${a.grounding.checked ?? 0} statements verified`}
      </p>
      {a.warnings.map((w) => (
        <p key={w} className="notice">{w}</p>
      ))}
      <ul className="plain">
        {a.statements.map((s, i) => (
          <li key={i} className="statement">
            <span className={`kind kind-${s.kind.toLowerCase()}`}>{KIND_LABEL[s.kind] ?? s.kind}</span> {s.text}
          </li>
        ))}
      </ul>
      {a.tools_used.length > 0 && (
        <details>
          <summary>Tools used and what they returned ({a.tools_used.length})</summary>
          {a.tools_used.map((t) => (
            <div key={t.call_id} className="tool">
              <p>
                <strong>{t.name}</strong> {t.ok ? "" : <span className="badge badge-fail">failed</span>}
              </p>
              <pre>{JSON.stringify(t.args, null, 2)}</pre>
              {t.error && <p className="notice notice-error">{t.error}</p>}
              <ul className="plain small">
                {t.facts.map((f) => (
                  <li key={f.id}>
                    <code>{f.id}</code> {f.label}: {f.value}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </details>
      )}
    </article>
  );
}

export function Analyst() {
  const status = useAsync((s) => api.analystStatus(s), []);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [history, setHistory] = useState<Schemas["AnalystResponse"][]>([]);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [history.length]);

  async function ask(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    setBusy(true);
    setError(null);
    try {
      const a = await api.analystAsk(question);
      setHistory((h) => [...h, a]);
      setQ("");
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section aria-labelledby="an-h">
        <h2 id="an-h">Ask about the data</h2>
        {status.data && (
          <p className="notice">
            <strong>How this works:</strong> the analyst only picks from {status.data.tools} fixed read-only tools; every number in an
            answer comes from a tool result and is checked. It labels each statement as a fact, interpretation, assumption or
            limitation, and shows the tools it used. Planner: {status.data.planner}. {status.data.llm_status}.
          </p>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void ask(q);
          }}
          aria-label="Ask a question"
        >
          <label htmlFor="q">Your question</label>
          <textarea id="q" value={q} maxLength={500} rows={2} onChange={(e) => setQ(e.target.value)} placeholder="For example: what were the busiest zones last week?" />
          <div className="row">
            <button type="submit" disabled={busy || !q.trim()}>
              {busy ? "Working…" : "Ask"}
            </button>
            <span className="muted small">{q.length}/500</span>
          </div>
        </form>
        <p className="muted small">Try one:</p>
        <ul className="chips">
          {EXAMPLES.map((e) => (
            <li key={e}>
              <button type="button" className="chip" onClick={() => void ask(e)} disabled={busy}>
                {e}
              </button>
            </li>
          ))}
        </ul>
        {error && <ErrorState error={error instanceof ApiError ? error : error} />}
      </section>
      <section aria-labelledby="conv-h" aria-live="polite">
        <h2 id="conv-h" className="sr-only">Answers</h2>
        {history.map((a, i) => (
          <Answer key={i} a={a} />
        ))}
        <div ref={end} />
      </section>
    </>
  );
}
