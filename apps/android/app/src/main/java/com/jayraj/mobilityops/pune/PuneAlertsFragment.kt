package com.jayraj.mobilityops.pune

import android.content.Context
import android.view.View
import android.widget.LinearLayout
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import com.jayraj.mobilityops.R
import com.jayraj.mobilityops.ui.Ui

/** Alerts: runs of hours where simulated demand left its forecast. They describe a departure, never a cause. */
class PuneAlertsFragment : PuneScreen() {
    private var events: List<EventItem>? = null
    private var error: String? = null

    override fun onNewData() {
        load({ PuneClient(api()).events(50) }, { events = it; error = null; redraw() }, { error = it.message; redraw() })
    }

    override fun render(c: Context) {
        header(c, "Alerts")
        content.addView(Ui.muted(c, "SIMULATED. At least two consecutive completed hours whose pooled deviation reaches 5σ, at least 1.5× (or at most 0.6×) the forecast, on at least 30 forecast trips."))
        val list = events ?: st.snapshot?.events
        if (list == null) {
            content.addView(Ui.muted(c, error ?: "Loading…"))
            return
        }
        if (list.isEmpty()) {
            content.addView(Ui.subheading(c, "No events so far today"))
            content.addView(Ui.muted(c, "Demand has stayed within its forecast range for long enough to count. Most days have none."))
        }
        list.forEach { content.addView(eventCard(c, it) { id -> PuneNav.zone(this, id) }) }
    }

    companion object {
        fun eventCard(c: Context, e: EventItem, open: (Int) -> Unit): View {
            val card = MaterialCardView(c).apply {
                setCardBackgroundColor(androidx.core.content.ContextCompat.getColor(c, R.color.surface))
                strokeColor = androidx.core.content.ContextCompat.getColor(c, if (e.severity == "high") R.color.fail else R.color.border)
                strokeWidth = Ui.dp(c, 2)
                radius = Ui.dp(c, 8).toFloat()
                cardElevation = 0f
            }
            val box = LinearLayout(c).apply { orientation = LinearLayout.VERTICAL; setPadding(Ui.dp(c, 12), Ui.dp(c, 10), Ui.dp(c, 12), Ui.dp(c, 10)) }
            box.addView(Ui.text(c, "${e.severity.uppercase()} ${if (e.kind == "surge") "surge" else "drop"} · ${e.zone}", 15f, R.color.text, true))
            box.addView(Ui.muted(c, "${PuneState.clock(e.start)} to ${PuneState.clock(e.end)} · SIMULATED"))
            val ratio = if (e.expected > 0) " (${String.format(java.util.Locale.US, "%.1f", e.actual / e.expected)}×)" else ""
            box.addView(Ui.body(c, "${PuneScreen.fmtInt(e.actual)} pickups against a forecast of ${PuneScreen.fmtInt(e.expected)}$ratio; deviation ${String.format(java.util.Locale.US, "%+.1f", e.score)} σ."))
            box.addView(Ui.muted(c, e.explanation))
            box.addView(MaterialButton(c).apply { text = "Zone details"; setOnClickListener { open(e.zoneId) } })
            card.addView(box)
            card.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                .apply { setMargins(0, Ui.dp(c, 6), 0, Ui.dp(c, 6)) }
            return card
        }
    }
}
