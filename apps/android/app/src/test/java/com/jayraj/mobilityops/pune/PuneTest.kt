package com.jayraj.mobilityops.pune

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private fun zone(id: Int, actual: Any? = 100.0, ratio: Any? = 1.0, status: String = "normal") = JSONObject()
    .put("id", id).put("actual", actual ?: JSONObject.NULL).put("forecast", 100.0).put("lo", 80.0).put("hi", 120.0)
    .put("ratio", ratio ?: JSONObject.NULL).put("z", 0.0).put("status", status).put("event_id", JSONObject.NULL)

private fun source(key: String, freshness: String, enabled: Boolean = true) = JSONObject()
    .put("key", key).put("label", key).put("provider", "p").put("data_class", "NEAR-REAL-TIME").put("modelled", true)
    .put("licence", "CC BY 4.0").put("note", "n").put("enabled", enabled)
    .put("disabled_reason", if (enabled) JSONObject.NULL else "no key").put("freshness", freshness)
    .put("interval_s", 900).put("age_s", 120.0).put("consecutive_failures", 0).put("last_error", JSONObject.NULL)

fun snapshotJson(
    seq: Long = 7,
    freshness: String = "LIVE",
    worker: String = "LIVE",
    actual: Any? = 500.0,
    serverTime: String = "2026-09-24T15:47:25.864762Z",
): JSONObject = JSONObject()
    .put("server_time", serverTime).put("window_end", "2026-09-24T21:17:25").put("selector", "now").put("window_note", "Now: hour so far")
    .put("data_label", "SIMULATED DEMAND (real weather and geography)").put("seq", seq).put("freshness", freshness)
    .put("worker", JSONObject().put("freshness", worker)).put("forecast_model", "m1")
    .put("zones", JSONArray().put(zone(1)).put(zone(2, null, null, "surge")))
    .put("totals", JSONObject().put("actual", actual ?: JSONObject.NULL).put("forecast", 600.0).put("lo", 400.0).put("hi", 800.0).put("ratio", 0.83))
    .put(
        "events",
        JSONArray().put(
            JSONObject().put("id", "e1").put("zone_id", 2).put("zone", "Kothrud").put("kind", "surge").put("severity", "high")
                .put("start", "2026-09-24T19:00:00").put("end", "2026-09-24T21:00:00").put("actual", 300.0)
                .put("expected", 120.0).put("score", 11.5).put("explanation", "no cause claimed"),
        ),
    )
    .put(
        "environment",
        JSONObject().put("temperature", JSONObject().put("value", 23.8).put("unit", "°C").put("freshness", "LIVE").put("modelled", true)),
    )
    .put("sources", JSONArray().put(source("open-meteo-forecast", "LIVE")).put(source("tomtom-traffic", "DISABLED", false)))

class ParseTest {
    @Test
    fun snapshotKeepsNullsAsNull() {
        val s = Parse.snapshot(snapshotJson(actual = null))
        assertNull(s.actual)
        assertEquals(600.0, s.forecast, 0.0)
        assertEquals(2, s.zones.size)
        assertNull(s.zones[1].actual)
        assertNull(s.zones[1].ratio)
        assertEquals("surge", s.zones[1].status)
        assertEquals(Freshness.LIVE, s.freshness)
        assertEquals("m1", s.forecastModel)
    }

    @Test
    fun environmentSourcesAndEventsParse() {
        val s = Parse.snapshot(snapshotJson())
        assertEquals(23.8, s.environment["temperature"]!!.value, 0.0)
        assertTrue(s.environment["temperature"]!!.modelled)
        assertEquals(2, s.sources.size)
        assertFalse(s.sources[1].enabled)
        assertEquals("no key", s.sources[1].disabledReason)
        assertEquals(Freshness.DISABLED, s.sources[1].freshness)
        assertEquals("Kothrud", s.events.single().zone)
    }

    @Test
    fun geometryAndSeriesParse() {
        val g = Parse.geometry(
            JSONObject().put("bbox", JSONArray(listOf(18.4, 73.7, 18.68, 74.02))).put("attribution", "© OSM")
                .put(
                    "zones",
                    JSONArray().put(
                        JSONObject().put("id", 1).put("name", "A").put("sector", "West").put("lat", 18.5).put("lon", 73.8)
                            .put("ring", JSONArray().put(JSONArray(listOf(73.7, 18.4))).put(JSONArray(listOf(73.9, 18.4))).put(JSONArray(listOf(73.9, 18.6)))),
                    ),
                ),
        )
        assertEquals(3, g.zones.single().ring.size)
        assertEquals(74.02, g.bbox[3], 0.0)
        val sr = Parse.series(
            JSONObject().put("today_actual", 10.0).put("today_forecast", 12.0).put("envelope_note", "wider")
                .put("series", JSONArray().put(JSONObject().put("hour", "2026-09-24T21:00:00").put("actual", JSONObject.NULL).put("forecast", 5.0).put("lo", 3.0).put("hi", 8.0).put("partial", true))),
        )
        assertNull(sr.points.single().actual)
        assertTrue(sr.points.single().partial)
    }

    @Test
    fun unknownFreshnessIsTreatedAsOfflineNeverLive() {
        assertEquals(Freshness.OFFLINE, Freshness.parse("SOMETHING_NEW"))
        assertEquals(Freshness.OFFLINE, Freshness.parse(null))
        assertEquals(Freshness.DISABLED, Freshness.parse("DISABLED"))
    }
}

class FreshnessTest {
    @Test
    fun ageIsPlainWords() {
        assertEquals("just now", ageText(0.0))
        assertEquals("42 s ago", ageText(42.0))
        assertEquals("5 min ago", ageText(300.0))
        assertEquals("3 h ago", ageText(3 * 3600.0))
        assertEquals("over a day ago", ageText(3 * 86400.0))
        assertEquals("never", ageText(null))
        assertEquals("just now", ageText(-3.0))
    }

    @Test
    fun badgesPairAGlyphWithAWord() {
        assertEquals("● LIVE", Freshness.LIVE.badge())
        assertTrue(Freshness.STALE.badge().startsWith("▲"))
        assertEquals("○ NOT CONFIGURED", Freshness.DISABLED.badge())
    }
}

class PuneStateTest {
    private fun hello(available: Boolean = true, snapshot: JSONObject? = snapshotJson()) = JSONObject()
        .put("server_time", "2026-09-24T15:47:10Z").put("available", available)
        .put("snapshot", snapshot ?: JSONObject.NULL).put("heartbeat_seconds", 10.0)

    private val t0 = 1_800_000_000_000L

    @Test
    fun helloGivesTheFirstSnapshotAndLiveLink() {
        val s = PuneState().onEvent("hello", hello(), t0)
        assertEquals(Link.LIVE, s.link)
        assertEquals(7L, s.snapshot!!.seq)
        assertEquals(t0, s.snapshotAtMs)
        assertFalse(s.unavailable)
        assertNull(s.notice())
    }

    @Test
    fun noWorkerIsReportedNotInvented() {
        val s = PuneState().onEvent("hello", hello(available = false, snapshot = null), t0)
        assertTrue(s.unavailable)
        assertNull(s.snapshot)
    }

    @Test
    fun reconnectingKeepsTheLastNumbersAndSaysTheyMayBeOld() {
        var s = PuneState().onEvent("snapshot", snapshotJson(), t0)
        s = s.withLink(Link.RECONNECTING, "lost")
        assertNotNull(s.snapshot)
        val n = s.notice()!!
        assertTrue(n.contains("Reconnecting"))
        assertTrue(n.contains("out of date"))
        assertTrue(n.contains("21:17"))
        assertFalse(n.contains("15:47")) // local Pune time, not the server's UTC clock
    }

    @Test
    fun offlineAndStoppedWorkerAndStaleSourcesEachHaveTheirOwnMessage() {
        val base = PuneState().onEvent("snapshot", snapshotJson(), t0)
        assertTrue(base.withLink(Link.OFFLINE, null).notice()!!.contains("offline"))
        val hb = base.onEvent("heartbeat", JSONObject().put("server_time", "2026-09-24T15:48:00Z").put("worker", JSONObject().put("freshness", "OFFLINE")), t0 + 1000)
        assertTrue(hb.notice()!!.contains("worker has stopped"))
        val stale = PuneState().onEvent("snapshot", snapshotJson(freshness = "STALE"), t0)
        assertTrue(stale.notice()!!.contains("stopped updating"))
        assertNull(PuneState().withLink(Link.CONNECTING, null).notice())
    }

    @Test
    fun heartbeatsKeepTheLinkAliveWithoutReplacingTheSnapshot() {
        var s = PuneState().onEvent("snapshot", snapshotJson(seq = 5), t0)
        s = s.onEvent("heartbeat", JSONObject().put("server_time", "2026-09-24T15:47:40Z").put("worker", JSONObject().put("freshness", "LIVE")), t0 + 20_000)
        assertEquals(5L, s.snapshot!!.seq)
        assertEquals(t0, s.snapshotAtMs)
        assertEquals(t0 + 20_000, s.lastMessageAtMs)
        assertEquals(Freshness.LIVE, s.workerFreshness)
    }

    @Test
    fun agesKeepCountingBetweenSnapshots() {
        val s = PuneState().onEvent("snapshot", snapshotJson(), t0)
        assertEquals(12.0, s.elapsedSeconds(t0 + 12_000), 0.001)
        assertEquals(0.0, s.elapsedSeconds(t0 - 5_000), 0.0) // a clock that ran backwards never gives a negative age
        assertEquals(0.0, PuneState().elapsedSeconds(t0), 0.0)
    }

    @Test
    fun unknownEventsChangeNothing() {
        val s = PuneState().onEvent("snapshot", snapshotJson(), t0)
        assertEquals(s, s.onEvent("mystery", JSONObject(), t0 + 1))
    }

    @Test
    fun serverClockOffsetIsMeasured() {
        val s = PuneState().onEvent("hello", hello(), java.time.Instant.parse("2026-09-24T15:47:00Z").toEpochMilli())
        assertEquals(10_000L, s.offsetMs)
    }
}

class MapColorsTest {
    private fun red(c: Int) = (c shr 16) and 0xFF

    @Test
    fun belowForecastIsBlueAboveIsOrangeAndItClamps() {
        assertEquals(MapColors.ratio(0.5), MapColors.ratio(0.1))
        assertEquals(MapColors.ratio(1.5), MapColors.ratio(9.0))
        assertTrue(red(MapColors.ratio(0.5)) < red(MapColors.ratio(1.5)))
        assertNotEquals(MapColors.ratio(1.0), MapColors.ratio(1.3))
    }

    @Test
    fun zonesWithNothingToJudgeAreIdle() {
        val z = ZoneValue(1, null, 100.0, 80.0, 120.0, null, null, "normal")
        assertEquals(MapColors.IDLE, MapColors.forLayer(MapLayer.RATIO, z, 0.0))
        assertEquals(MapColors.IDLE, MapColors.forLayer(MapLayer.RATIO, z.copy(forecast = 0.2, ratio = 3.0), 0.0))
        assertEquals(MapColors.IDLE, MapColors.forLayer(MapLayer.EVENTS, z, 0.0))
        assertEquals(MapColors.IDLE, MapColors.forLayer(MapLayer.RATIO, null, 0.0))
        assertNotEquals(MapColors.forLayer(MapLayer.EVENTS, z.copy(status = "surge"), 0.0), MapColors.forLayer(MapLayer.EVENTS, z.copy(status = "drop"), 0.0))
    }

    @Test
    fun theRampGetsDarkerWithDemand() {
        assertTrue(red(MapColors.ramp(0.0, 100.0)) > red(MapColors.ramp(100.0, 100.0)))
        assertEquals(MapColors.ramp(0.0, 0.0), MapColors.ramp(0.0, 100.0))
    }

    @Test
    fun theProjectionHasNorthUpAndTheStudyBoxAspect() {
        val p = Projection(doubleArrayOf(18.4, 73.7, 18.68, 74.02))
        assertEquals(0.0, p.y(18.68), 1e-9)
        assertEquals(0.28, p.y(18.4), 1e-9)
        assertEquals(0.0, p.x(73.7), 1e-9)
        assertTrue(p.width > 0.30 && p.width < 0.32)
    }
}
