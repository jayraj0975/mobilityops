package com.jayraj.mobilityops.pune

import com.jayraj.mobilityops.net.ApiClient

/** Typed reads of the Pune state endpoints. Blocking: call off the main thread. */
class PuneClient(private val api: ApiClient) {
    fun snapshot(at: String) = Parse.snapshot(api.getObject("/api/v1/state/snapshot", mapOf("at" to at)))
    fun geometry() = Parse.geometry(api.getObject("/api/v1/state/geometry", null))
    fun series(back: Int = 24, ahead: Int = 24) =
        Parse.series(api.getObject("/api/v1/state/series", mapOf("back" to "$back", "ahead" to "$ahead")))
    fun zone(id: Int) = Parse.zoneDetail(api.getObject("/api/v1/state/zones/$id", null))
    fun events(limit: Int = 50): List<EventItem> {
        val a = api.getArray("/api/v1/state/events", mapOf("limit" to "$limit"))
        return List(a.length()) { Parse.event(a.getJSONObject(it)) }
    }
    fun quality() = Parse.quality(api.getObject("/api/v1/state/quality", null))
    fun sources(): List<SourceState> {
        val a = api.getArray("/api/v1/state/sources", null)
        return List(a.length()) { Parse.source(a.getJSONObject(it)) }
    }
}
