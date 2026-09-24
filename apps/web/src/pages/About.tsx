import type { Schemas } from "../api/client";

const REPO = "https://github.com/jayraj0975/mobilityops";

export function About({ meta }: { meta: Schemas["Meta"] }) {
  const synthetic = meta.synthetic || meta.mode === "sample";
  return (
    <>
      <section aria-labelledby="what-h">
        <h2 id="what-h">What this is</h2>
        <p>
          MobilityOps is a portfolio project that turns public NYC yellow-taxi trip records into an analytics platform: a
          quality-checked data pipeline, demand analytics, a day-ahead forecast per taxi zone, anomaly detection on the
          forecast errors, a simulated vehicle-repositioning optimiser, and a controlled analyst that answers questions
          from read-only tools.
        </p>
        <p>
          Every section states what its numbers are and what they are not. Nothing here is a live feed, and nothing here
          is operational advice.
        </p>
      </section>

      <section aria-labelledby="data-h">
        <h2 id="data-h">The data on this site</h2>
        <p>
          <strong>{meta.data_label}</strong>
          {synthetic
            ? ": generated for tests and demos; these are not real trips."
            : `: NYC Taxi and Limousine Commission yellow-taxi trip records, ${meta.data_start.slice(0, 10)} onward, with daily weather for context. The TLC publishes these records openly; this site serves aggregates (pickups per zone per hour), not individual trips.`}
        </p>
        <p className="muted small">
          Sources and licences are listed in the repository (docs/DATA_SOURCES.md). This project is not affiliated with or
          endorsed by the TLC or the City of New York.
        </p>
      </section>

      <section aria-labelledby="how-h">
        <h2 id="how-h">How to read each section</h2>
        <ul>
          <li>
            <strong>Demand</strong>: what happened. Counts of pickups by zone, hour and day, with comparisons between
            periods.
          </li>
          <li>
            <strong>Forecast</strong>: day-ahead estimates issued at midnight using only earlier days, evaluated on time
            blocks the model never saw and compared with simple baselines. Intervals are calibrated per demand level.
          </li>
          <li>
            <strong>Anomalies</strong>: stretches where demand differed from the forecast by more than the usual error.
            They are candidates to look at, not explanations. The real data has no ground-truth labels, so the precision of
            these flags is unverified.
          </li>
          <li>
            <strong>Scenarios</strong>: a <em>simulated</em> repositioning plan under explicit assumptions. It shows what a
            plan would do in the model, not what would happen on the street. An infeasible scenario is a result, not an
            error.
          </li>
          <li>
            <strong>Analyst</strong>: questions are turned into calls to read-only tools; the answer is assembled from the
            tool results and each sentence is labelled as fact, interpretation, assumption or limitation. It cannot change
            anything.
          </li>
        </ul>
      </section>

      <section aria-labelledby="lim-h">
        <h2 id="lim-h">Limits worth knowing</h2>
        <ul>
          <li>The real data covers a few months, so yearly seasonality and long holidays are not learned.</li>
          <li>Relationships shown are associations. Nothing here establishes a cause.</li>
          <li>The boosted-tree forecast beats the best simple baseline by a modest, measured margin, not by a lot.</li>
          <li>The analyst has been tested on question sets written by the author; those are not independent users.</li>
          <li>This is a demo service: requests are rate limited and the data can be older than today.</li>
        </ul>
      </section>

      <section aria-labelledby="src-h">
        <h2 id="src-h">Source and documentation</h2>
        <p>
          <a href={REPO}>Source code, architecture notes, evaluation reports and decisions</a> are public. The API is
          documented at <a href="/docs">/docs</a>.
        </p>
      </section>
    </>
  );
}
