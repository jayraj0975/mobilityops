package com.jayraj.mobilityops.pune

import android.content.Context
import com.jayraj.mobilityops.ui.Ui

/** Home: the numbers that matter right now, each with its data class and freshness. */
class PuneHomeFragment : PuneScreen() {
    private var series: Series? = null
    private var seriesError: String? = null

    override fun onNewData() {
        load({ PuneClient(api()).series() }, { series = it; seriesError = null; redraw() }, { seriesError = it.message; redraw() })
    }

    override fun render(c: Context) {
        header(c, "Pune now")
        val s = st.snapshot ?: return
        val env = s.environment
        val tiles = ArrayList<Array<String>>()
        tiles.add(arrayOf("Simulated pickups, this hour", fmtInt(s.actual), listOfNotNull(pct(s.ratio), "SIMULATED").joinToString(" · ")))
        tiles.add(arrayOf("Forecast, this hour", fmtInt(s.forecast), "PREDICTED · ${fmtInt(s.lo)} to ${fmtInt(s.hi)} (zone ranges summed)"))
        val sr = series
        tiles.add(
            arrayOf(
                "Today so far", sr?.let { fmtInt(it.todayActual) } ?: (seriesError ?: "…"),
                sr?.let { "${pct(if (it.todayForecast > 0) it.todayActual / it.todayForecast else null) ?: ""} · SIMULATED" } ?: "SIMULATED",
            ),
        )
        tiles.add(arrayOf("Events today", "${s.events.size}", if (s.events.isEmpty()) "None detected so far · SIMULATED" else "Highest: ${s.events.first().severity} · SIMULATED"))
        val t = env["temperature"]
        tiles.add(
            arrayOf(
                "Weather", t?.let { String.format(java.util.Locale.US, "%.1f °C", it.value) } ?: "n/a",
                (env["precipitation"]?.let { "Rain ${it.value} mm · " } ?: "") + "NEAR-REAL-TIME · MODELLED · " +
                    (t?.freshness?.badge() ?: "no reading"),
            ),
        )
        val aqi = env["us_aqi"]
        tiles.add(arrayOf("Air quality (US AQI)", aqi?.let { fmtInt(it.value) } ?: "n/a", "MODELLED, not a station · " + (aqi?.freshness?.badge() ?: "no reading")))
        content.addView(Ui.kpiGrid(c, tiles.map { it as Array<String> }))
        content.addView(Ui.muted(c, s.windowNote))

        content.addView(Ui.subheading(c, "Events today"))
        if (s.events.isEmpty()) content.addView(Ui.muted(c, "No events so far. An event needs at least two consecutive hours far outside the forecast range; most days have none."))
        s.events.take(3).forEach { content.addView(PuneAlertsFragment.eventCard(c, it) { id -> PuneNav.zone(this, id) }) }

        content.addView(Ui.subheading(c, "Data sources"))
        s.sources.filter { it.enabled && it.freshness != Freshness.NOT_PERIODIC }.forEach { src ->
            content.addView(Ui.body(c, src.label))
            content.addView(freshnessLine(c, src.freshness, src.ageSeconds?.plus(elapsed)))
        }
        content.addView(Ui.muted(c, "Weather data by Open-Meteo.com (CC BY 4.0). Map data © OpenStreetMap contributors (ODbL)."))
    }
}
