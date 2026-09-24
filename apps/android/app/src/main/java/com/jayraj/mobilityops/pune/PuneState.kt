package com.jayraj.mobilityops.pune

import org.json.JSONObject

enum class Link { CONNECTING, LIVE, RECONNECTING, OFFLINE }

/**
 * What the app knows about Pune right now. Pure data with pure transitions, so every behaviour
 * (reconnecting, silence, a worker that stopped) is testable without a device.
 */
data class PuneState(
    val link: Link = Link.CONNECTING,
    val snapshot: Snapshot? = null,
    /** Device clock (ms) when the newest snapshot arrived. */
    val snapshotAtMs: Long? = null,
    val lastMessageAtMs: Long? = null,
    val workerFreshness: Freshness? = null,
    val unavailable: Boolean = false,
    val message: String? = null,
    /** server time minus device time at the newest message; corrects for a wrong device clock. */
    val offsetMs: Long = 0,
) {
    fun withLink(link: Link, message: String?): PuneState = copy(link = link, message = message)

    /** Apply one server-sent event (`hello`, `snapshot`, `heartbeat`). Unknown events change nothing. */
    fun onEvent(name: String, data: JSONObject, nowMs: Long): PuneState = when (name) {
        "hello" -> {
            val snap = if (data.isNull("snapshot")) null else Parse.snapshot(data.getJSONObject("snapshot"))
            copy(
                link = Link.LIVE, message = null, unavailable = !data.optBoolean("available", false),
                snapshot = snap ?: snapshot, snapshotAtMs = if (snap != null) nowMs else snapshotAtMs,
                lastMessageAtMs = nowMs, offsetMs = skew(data.optString("server_time"), nowMs),
            )
        }
        "snapshot" -> {
            val snap = Parse.snapshot(data)
            copy(
                link = Link.LIVE, message = null, unavailable = false, snapshot = snap, snapshotAtMs = nowMs,
                lastMessageAtMs = nowMs, offsetMs = skew(snap.serverTime, nowMs),
            )
        }
        "heartbeat" -> copy(
            lastMessageAtMs = nowMs,
            workerFreshness = Freshness.parse(data.optJSONObject("worker")?.optString("freshness")),
            offsetMs = skew(data.optString("server_time"), nowMs),
        )
        else -> this
    }

    /** Seconds since the newest snapshot arrived: ages keep counting between updates. */
    fun elapsedSeconds(nowMs: Long): Double = snapshotAtMs?.let { maxOf(0.0, (nowMs - it) / 1000.0) } ?: 0.0

    /** The reason the numbers may not be current, in words, or null when all is well. */
    fun notice(): String? {
        val last = snapshot?.let { " The numbers shown are from ${clock(it.windowEnd)}." } ?: ""
        val worker = workerFreshness ?: snapshot?.workerFreshness
        return when {
            link == Link.OFFLINE -> "This device is offline.$last"
            link == Link.CONNECTING -> null
            link == Link.RECONNECTING -> "Reconnecting to the server.$last They may be out of date."
            worker == Freshness.OFFLINE || worker == Freshness.STALE ->
                "The ingestion worker has stopped, so nothing new is arriving.$last Values are held from its last run."
            snapshot?.freshness == Freshness.STALE || snapshot?.freshness == Freshness.OFFLINE ->
                "One or more data sources have stopped updating.$last See Data status for which."
            else -> null
        }
    }

    companion object {
        private fun skew(serverTime: String, nowMs: Long): Long =
            com.jayraj.mobilityops.util.Times.parseIso(serverTime).let { if (it <= 0) 0 else it - nowMs }

        /** hh:mm of an ISO timestamp, as written. */
        fun clock(iso: String): String = Regex("T(\\d{2}):(\\d{2})").find(iso)?.let { "${it.groupValues[1]}:${it.groupValues[2]}" } ?: iso
    }
}
