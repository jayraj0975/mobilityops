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
        list.forEach {
            content.addView(
                eventCard(c, it, { id -> PuneNav.zone(this, id) }) { id, ok, err ->
                    load({ PuneClient(api()).eventImpact(id).scenario }, { ok(it) }, { err(it.message ?: "Something went wrong") })
                },
            )
        }
    }

    companion object {
        /** ``onImpact``, when given, adds a "Recommended response" button that lazily fetches and
         * shows a RECOMMENDED repositioning scenario (see state/events/{id}/impact). */
        fun eventCard(
            c: Context,
            e: EventItem,
            open: (Int) -> Unit,
            onImpact: ((String, (RepositioningScenario?) -> Unit, (String) -> Unit) -> Unit)? = null,
        ): View {
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
            val buttons = LinearLayout(c).apply { orientation = LinearLayout.HORIZONTAL }
            buttons.addView(MaterialButton(c).apply { text = "Zone details"; setOnClickListener { open(e.zoneId) } })
            if (onImpact != null) {
                val impactButton = MaterialButton(c).apply { text = "Recommended response" }
                buttons.addView(impactButton)
                impactButton.setOnClickListener {
                    impactButton.isEnabled = false
                    impactButton.text = "Loading…"
                    onImpact(
                        e.id,
                        { scenario -> box.addView(impactView(c, scenario)); buttons.removeView(impactButton) },
                        { message -> box.addView(Ui.muted(c, "Could not load a response: $message")); buttons.removeView(impactButton) },
                    )
                }
            }
            box.addView(buttons)
            card.addView(box)
            card.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                .apply { setMargins(0, Ui.dp(c, 6), 0, Ui.dp(c, 6)) }
            return card
        }

        private fun impactView(c: Context, s: RepositioningScenario?): View {
            val box = LinearLayout(c).apply { orientation = LinearLayout.VERTICAL }
            if (s == null) {
                box.addView(Ui.muted(c, "No other zone lies within repositioning range of this event."))
                return box
            }
            box.addView(Ui.muted(c, s.label))
            if (s.status == "infeasible" || s.status == "no_solution") {
                box.addView(Ui.body(c, s.message))
                return box
            }
            val sharePct = { v: Double? -> if (v == null) "n/a" else String.format(java.util.Locale.US, "%.0f%%", v * 100) }
            box.addView(
                Ui.body(
                    c,
                    "PREDICTED: without repositioning, ${sharePct(s.serviceShareBefore)} of demand across the nearby " +
                        "zones would be served (${PuneScreen.fmtInt(s.servedBefore)} of ${PuneScreen.fmtInt(s.demandTotal)} " +
                        "trips, ${s.fleet} vehicles assumed).",
                ),
            )
            if (s.moves.isEmpty()) {
                box.addView(Ui.body(c, "RECOMMENDED: no repositioning move improves on that under these assumptions."))
            } else {
                box.addView(
                    Ui.body(
                        c,
                        "RECOMMENDED: move ${s.vehiclesMoved} vehicle${if (s.vehiclesMoved == 1) "" else "s"} " +
                            "(${PuneScreen.fmtInt(s.kmTotal)} km total) to reach ${sharePct(s.serviceShareAfter)} served.",
                    ),
                )
                s.moves.forEach {
                    box.addView(Ui.muted(c, "Zone ${it.fromZone} → zone ${it.toZone}: ${it.vehicles.toInt()} vehicle(s) (${it.km} km)"))
                }
            }
            return box
        }
    }
}
