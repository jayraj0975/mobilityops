package com.jayraj.mobilityops.pune

import org.json.JSONArray
import org.json.JSONObject

data class ZoneValue(
    val id: Int,
    val actual: Double?,
    val forecast: Double,
    val lo: Double,
    val hi: Double,
    val ratio: Double?,
    val z: Double?,
    val status: String,
)

data class EventItem(
    val id: String,
    val zoneId: Int,
    val zone: String,
    val kind: String,
    val severity: String,
    val start: String,
    val end: String,
    val actual: Double,
    val expected: Double,
    val score: Double,
    val explanation: String,
)

data class SourceState(
    val key: String,
    val label: String,
    val provider: String,
    val dataClass: String,
    val modelled: Boolean,
    val licence: String,
    val note: String,
    val enabled: Boolean,
    val disabledReason: String?,
    val freshness: Freshness,
    val ageSeconds: Double?,
    val consecutiveFailures: Int,
    val lastError: String?,
)

data class Reading(val value: Double, val unit: String, val freshness: Freshness, val modelled: Boolean)

data class Snapshot(
    val serverTime: String,
    val selector: String,
    val windowNote: String,
    /** Naive local (Pune) time the window ends at: the moment these numbers describe. */
    val windowEnd: String,
    val dataLabel: String,
    val seq: Long,
    val freshness: Freshness,
    val workerFreshness: Freshness,
    val forecastModel: String?,
    val zones: List<ZoneValue>,
    val actual: Double?,
    val forecast: Double,
    val lo: Double,
    val hi: Double,
    val ratio: Double?,
    val events: List<EventItem>,
    val environment: Map<String, Reading>,
    val sources: List<SourceState>,
)

data class ZoneGeom(val id: Int, val name: String, val sector: String, val lat: Double, val lon: Double, val ring: List<DoubleArray>)

data class Geometry(val bbox: DoubleArray, val zones: List<ZoneGeom>, val attribution: String)

data class SeriesPoint(val hour: String, val actual: Double?, val forecast: Double?, val lo: Double?, val hi: Double?, val partial: Boolean)

data class Series(val points: List<SeriesPoint>, val todayActual: Double, val todayForecast: Double, val note: String)

data class ZoneDetail(
    val id: Int,
    val name: String,
    val sector: String,
    val points: List<SeriesPoint>,
    val events: List<EventItem>,
    val todayActual: Double,
    val todayForecast: Double,
)

data class QualityCheck(val check: String, val status: String, val message: String)

data class Quality(
    val builtAt: String?,
    val windowStart: String?,
    val windowEnd: String?,
    val daysBehind: Int?,
    val checks: List<QualityCheck>,
    val notes: List<String>,
)

private fun JSONObject.dbl(name: String): Double? = if (isNull(name) || !has(name)) null else getDouble(name)
private fun JSONObject.str(name: String): String? = if (isNull(name) || !has(name)) null else getString(name)
private fun <T> JSONArray?.map(f: (JSONObject) -> T): List<T> {
    if (this == null) return emptyList()
    val out = ArrayList<T>(length())
    for (i in 0 until length()) out.add(f(getJSONObject(i)))
    return out
}

/** Parsers for the Pune state documents. A missing or null field becomes null, never a guess. */
object Parse {
    fun zone(o: JSONObject) = ZoneValue(
        o.getInt("id"), o.dbl("actual"), o.getDouble("forecast"), o.getDouble("lo"), o.getDouble("hi"),
        o.dbl("ratio"), o.dbl("z"), o.optString("status", "normal"),
    )

    fun event(o: JSONObject) = EventItem(
        o.getString("id"), o.getInt("zone_id"), o.getString("zone"), o.getString("kind"), o.getString("severity"),
        o.getString("start"), o.getString("end"), o.getDouble("actual"), o.getDouble("expected"),
        o.getDouble("score"), o.optString("explanation", ""),
    )

    fun source(o: JSONObject) = SourceState(
        o.getString("key"), o.getString("label"), o.getString("provider"), o.getString("data_class"),
        o.optBoolean("modelled"), o.optString("licence", ""), o.optString("note", ""), o.optBoolean("enabled", true),
        o.str("disabled_reason"), Freshness.parse(o.str("freshness")), o.dbl("age_s"),
        o.optInt("consecutive_failures"), o.str("last_error"),
    )

    private val ENV_KEYS = listOf("temperature", "humidity", "precipitation", "wind", "pm2_5", "pm10", "us_aqi")

    fun snapshot(o: JSONObject): Snapshot {
        val totals = o.getJSONObject("totals")
        val env = o.optJSONObject("environment")
        val readings = HashMap<String, Reading>()
        if (env != null) {
            for (k in ENV_KEYS) {
                val r = env.optJSONObject(k) ?: continue
                readings[k] = Reading(r.getDouble("value"), r.optString("unit"), Freshness.parse(r.str("freshness")), r.optBoolean("modelled"))
            }
        }
        return Snapshot(
            serverTime = o.getString("server_time"),
            selector = o.getString("selector"),
            windowNote = o.optString("window_note"),
            windowEnd = o.optString("window_end", o.getString("server_time")),
            dataLabel = o.getString("data_label"),
            seq = o.optLong("seq"),
            freshness = Freshness.parse(o.str("freshness")),
            workerFreshness = Freshness.parse(o.optJSONObject("worker")?.str("freshness")),
            forecastModel = o.str("forecast_model"),
            zones = o.optJSONArray("zones").map(::zone),
            actual = totals.dbl("actual"),
            forecast = totals.getDouble("forecast"),
            lo = totals.getDouble("lo"),
            hi = totals.getDouble("hi"),
            ratio = totals.dbl("ratio"),
            events = o.optJSONArray("events").map(::event),
            environment = readings,
            sources = o.optJSONArray("sources").map(::source),
        )
    }

    fun geometry(o: JSONObject): Geometry {
        val b = o.getJSONArray("bbox")
        return Geometry(
            DoubleArray(b.length()) { b.getDouble(it) },
            o.getJSONArray("zones").map { z ->
                val r = z.getJSONArray("ring")
                ZoneGeom(
                    z.getInt("id"), z.getString("name"), z.getString("sector"), z.getDouble("lat"), z.getDouble("lon"),
                    List(r.length()) { i -> r.getJSONArray(i).let { doubleArrayOf(it.getDouble(0), it.getDouble(1)) } },
                )
            },
            o.optString("attribution"),
        )
    }

    private fun point(p: JSONObject) = SeriesPoint(
        p.getString("hour"), p.dbl("actual"), p.dbl("forecast"), p.dbl("lo"), p.dbl("hi"), p.optBoolean("partial"),
    )

    fun series(o: JSONObject) = Series(
        o.getJSONArray("series").map(::point), o.getDouble("today_actual"), o.getDouble("today_forecast"),
        o.optString("envelope_note"),
    )

    fun zoneDetail(o: JSONObject) = ZoneDetail(
        o.getInt("id"), o.getString("name"), o.getString("sector"), o.getJSONArray("series").map(::point),
        o.optJSONArray("events").map(::event), o.getDouble("today_actual"), o.getDouble("today_forecast"),
    )

    fun quality(o: JSONObject): Quality {
        val db = o.getJSONObject("database")
        val notes = o.optJSONArray("notes")
        return Quality(
            db.str("built_at_utc"), db.str("window_start"), db.str("window_end"),
            if (db.isNull("days_behind") || !db.has("days_behind")) null else db.getInt("days_behind"),
            db.optJSONArray("checks").map { QualityCheck(it.getString("check"), it.getString("status"), it.getString("message")) },
            List(notes?.length() ?: 0) { notes!!.getString(it) },
        )
    }
}
