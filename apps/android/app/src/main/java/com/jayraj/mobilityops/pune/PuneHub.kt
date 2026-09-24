package com.jayraj.mobilityops.pune

import com.jayraj.mobilityops.net.ApiClient
import com.jayraj.mobilityops.net.SseClient
import com.jayraj.mobilityops.util.Async
import org.json.JSONObject

/**
 * One shared connection to the Pune state stream for every screen. It opens when the first screen
 * needs it and closes when the last one leaves, so a backgrounded app holds no connection.
 * All state changes happen on the main thread.
 */
object PuneHub {
    var state: PuneState = PuneState()
        private set
    private val listeners = LinkedHashSet<(PuneState) -> Unit>()
    private var client: SseClient? = null
    private var users = 0

    fun acquire(api: ApiClient) {
        users++
        if (client == null) {
            state = PuneState()
            client = SseClient(api, "/api/v1/state/stream", object : SseClient.Listener {
                override fun onState(s: SseClient.State, message: String?) {
                    Async.onMain {
                        state = when (s) {
                            SseClient.State.CONNECTING -> state.withLink(Link.CONNECTING, null)
                            SseClient.State.LIVE -> state.withLink(Link.LIVE, null)
                            SseClient.State.RECONNECTING -> state.withLink(Link.RECONNECTING, message)
                        }
                        publish()
                    }
                }

                override fun onEvent(name: String, data: JSONObject) {
                    Async.onMain {
                        state = try {
                            state.onEvent(name, data, System.currentTimeMillis())
                        } catch (e: org.json.JSONException) {
                            state // a malformed event must not end the session
                        }
                        publish()
                    }
                }
            }).also { it.start() }
        }
    }

    fun release() {
        users = maxOf(0, users - 1)
        if (users == 0) {
            client?.stop()
            client = null
        }
    }

    /** Subscribe on the main thread; returns a function that unsubscribes. */
    fun observe(l: (PuneState) -> Unit): () -> Unit {
        listeners.add(l)
        l(state)
        return { listeners.remove(l) }
    }

    private fun publish() {
        for (l in listeners.toList()) l(state)
    }
}
