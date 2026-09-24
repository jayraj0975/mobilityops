package com.jayraj.mobilityops.pune

import android.content.Context
import com.google.android.material.button.MaterialButton
import com.jayraj.mobilityops.ui.Ui

/** Data status: the connection, the worker, every source with its freshness, and the quality checks. */
class PuneStatusFragment : PuneScreen() {
    private var quality: Quality? = null
    private var error: String? = null

    override fun onNewData() {
        load({ PuneClient(api()).quality() }, { quality = it; error = null; redraw() }, { error = it.message; redraw() })
    }

    override fun render(c: Context) {
        header(c, "Data status")
        content.addView(Ui.subheading(c, "This connection"))
        content.addView(Ui.body(c, "Link: ${st.link.name.lowercase()}${st.message?.let { " ($it)" } ?: ""}"))
        content.addView(Ui.body(c, "Last message: ${ageText(st.lastMessageAtMs?.let { (now - it) / 1000.0 })}"))
        content.addView(Ui.body(c, "Newest snapshot: ${ageText(if (st.snapshotAtMs == null) null else elapsed)}"))
        content.addView(Ui.body(c, "Clock offset (server minus device): ${String.format(java.util.Locale.US, "%.1f", st.offsetMs / 1000.0)} s"))
        val s = st.snapshot
        if (s != null) {
            content.addView(freshnessLine(c, s.workerFreshness, null, "Ingestion worker: "))
            content.addView(freshnessLine(c, s.freshness, null, "All data: "))
            content.addView(Ui.subheading(c, "Sources"))
            s.sources.forEach { src ->
                content.addView(Ui.body(c, "${src.label} (${src.provider})"))
                content.addView(freshnessLine(c, src.freshness, src.ageSeconds?.plus(elapsed)))
                content.addView(Ui.muted(c, "${src.dataClass}${if (src.modelled) " · MODELLED" else ""} · ${src.licence}"))
                content.addView(Ui.muted(c, if (src.enabled) src.note else "${src.disabledReason ?: "Not configured"}. ${src.note}"))
                if (src.consecutiveFailures > 0) {
                    content.addView(Ui.muted(c, "${src.consecutiveFailures} failed polls in a row: ${src.lastError ?: "unknown error"}"))
                }
            }
        }
        val q = quality
        content.addView(Ui.subheading(c, "Analytical database"))
        if (q == null) {
            content.addView(Ui.muted(c, error ?: "Loading…"))
        } else {
            content.addView(Ui.body(c, "Built ${q.builtAt ?: "n/a"} · window ${q.windowStart} to ${q.windowEnd} · ${q.daysBehind ?: "?"} days behind today"))
            q.checks.forEach { content.addView(Ui.muted(c, "${if (it.status == "PASS") "● PASS" else "▲ ${it.status}"}  ${it.check}: ${it.message}")) }
            q.notes.forEach { content.addView(Ui.muted(c, it)) }
        }
        content.addView(
            MaterialButton(c).apply {
                text = "Server settings"
                setOnClickListener { PuneNav.settings(this@PuneStatusFragment) }
            },
        )
    }
}
