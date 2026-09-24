package com.jayraj.mobilityops.pune

import android.content.Context
import android.os.Bundle
import com.jayraj.mobilityops.R
import com.jayraj.mobilityops.ui.LineChartView
import com.jayraj.mobilityops.ui.Ui

/** Zone details: one zone's simulated day against its forecast range, and its events. */
class PuneZoneFragment : PuneScreen() {
    private var detail: ZoneDetail? = null
    private var error: String? = null
    private val zoneId: Int get() = requireArguments().getInt(ARG)

    override fun onNewData() {
        val id = zoneId
        load({ PuneClient(api()).zone(id) }, { detail = it; error = null; redraw() }, { error = it.message; redraw() })
    }

    override fun render(c: Context) {
        val d = detail
        header(c, d?.name ?: "Zone")
        if (d == null) {
            content.addView(Ui.muted(c, error ?: "Loading…"))
            return
        }
        content.addView(Ui.muted(c, "${d.sector} sector · zone ${d.id}"))
        content.addView(
            Ui.kpiGrid(
                c,
                listOf(
                    arrayOf("Today so far", fmtInt(d.todayActual), "SIMULATED"),
                    arrayOf("Forecast, same hours", fmtInt(d.todayForecast), pct(if (d.todayForecast > 0) d.todayActual / d.todayForecast else null) ?: ""),
                ),
            ),
        )
        val chart = Ui.chart(c)
        fun col(f: (SeriesPoint) -> Double?) = DoubleArray(d.points.size) { f(d.points[it]) ?: Double.NaN }
        chart.setData(
            d.points.map { PuneState.clock(it.hour) }.toTypedArray(),
            listOf(
                LineChartView.Series("Simulated pickups", color(R.color.series1), col { it.actual }, false),
                LineChartView.Series("Forecast", color(R.color.series2), col { it.forecast }, true),
                LineChartView.Series("80% low", color(R.color.muted), col { it.lo }, true),
                LineChartView.Series("80% high", color(R.color.muted), col { it.hi }, true),
            ),
            "${d.name}: simulated pickups per hour against the forecast and its range.",
        )
        content.addView(chart)
        content.addView(Ui.subheading(c, "Events in this zone"))
        if (d.events.isEmpty()) content.addView(Ui.muted(c, "None detected."))
        d.events.forEach { content.addView(PuneAlertsFragment.eventCard(c, it) { }) }
    }

    companion object {
        private const val ARG = "zone"
        fun of(id: Int) = PuneZoneFragment().apply { arguments = Bundle().apply { putInt(ARG, id) } }
    }
}
