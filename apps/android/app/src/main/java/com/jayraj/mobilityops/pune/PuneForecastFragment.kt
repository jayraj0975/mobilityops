package com.jayraj.mobilityops.pune

import android.content.Context
import com.jayraj.mobilityops.R
import com.jayraj.mobilityops.ui.LineChartView
import com.jayraj.mobilityops.ui.Ui

/** Forecast: simulated demand against the forecast and its 80% range, city wide. */
class PuneForecastFragment : PuneScreen() {
    private var series: Series? = null
    private var error: String? = null
    private var perf: org.json.JSONObject? = null

    override fun onNewData() {
        load({ PuneClient(api()).series(30, 24) }, { series = it; error = null; redraw() }, { error = it.message; redraw() })
        if (perf == null) load({ api().getObject("/api/v1/forecast/performance", null) }, { perf = it; redraw() }, { })
    }

    override fun render(c: Context) {
        header(c, "Forecast")
        val sr = series
        if (sr == null) {
            content.addView(Ui.muted(c, error ?: "Loading…"))
            return
        }
        content.addView(Ui.body(c, "PREDICTED: the day-ahead forecast, made from data up to yesterday, with an 80% range per zone."))
        val chart: LineChartView = Ui.chart(c)
        val labels = sr.points.map { PuneState.clock(it.hour) }.toTypedArray()
        fun col(f: (SeriesPoint) -> Double?) = DoubleArray(sr.points.size) { f(sr.points[it]) ?: Double.NaN }
        chart.setData(
            labels,
            listOf(
                LineChartView.Series("Simulated pickups", color(R.color.series1), col { it.actual }, false),
                LineChartView.Series("Forecast", color(R.color.series2), col { it.forecast }, true),
                LineChartView.Series("80% low", color(R.color.muted), col { it.lo }, true),
                LineChartView.Series("80% high", color(R.color.muted), col { it.hi }, true),
            ),
            "City simulated pickups per hour against the forecast and its 80 percent range. Today so far ${fmtInt(sr.todayActual)} against a forecast of ${fmtInt(sr.todayForecast)}.",
        )
        content.addView(chart)
        content.addView(Ui.muted(c, sr.note.replace("The shaded range", "The dashed range lines")))
        content.addView(
            Ui.kpiGrid(
                c,
                listOf(
                    arrayOf("Today so far", fmtInt(sr.todayActual), "SIMULATED"),
                    arrayOf("Forecast, same hours", fmtInt(sr.todayForecast), pct(if (sr.todayForecast > 0) sr.todayActual / sr.todayForecast else null) ?: ""),
                ),
            ),
        )
        content.addView(Ui.subheading(c, "This model"))
        content.addView(
            Ui.muted(
                c,
                "Model ${st.snapshot?.forecastModel ?: "not available"}. It uses yesterday, last week and calendar features " +
                    "(including Maharashtra holidays) but not the weather, so on a dry day after rainy ones it forecasts too high.",
            ),
        )
        perf?.let { p ->
            val overall = p.optJSONObject("overall")
            val lgb = overall?.optJSONObject("lightgbm")
            val base = p.optString("best_baseline")
            val bl = overall?.optJSONObject(base)
            if (lgb != null && !lgb.isNull("wape")) {
                content.addView(Ui.subheading(c, "How accurate has it been?"))
                content.addView(
                    Ui.body(
                        c,
                        "WAPE ${String.format(java.util.Locale.US, "%.1f%%", lgb.getDouble("wape") * 100)}" +
                            (if (bl != null && !bl.isNull("wape")) " against ${String.format(java.util.Locale.US, "%.1f%%", bl.getDouble("wape") * 100)} for the best baseline ($base)." else "."),
                    ),
                )
                content.addView(Ui.muted(c, "Measured on simulated demand: it shows the pipeline works, not how well it would forecast real Pune traffic."))
            }
        }
    }
}
