package com.jayraj.mobilityops.net;

import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.Reader;
import java.net.HttpURLConnection;
import java.nio.charset.StandardCharsets;

import org.json.JSONException;
import org.json.JSONObject;

/**
 * Follows the server's live event stream on its own thread and reconnects when it drops.
 *
 * <p>The read timeout doubles as the silence watchdog: the server sends a keep-alive every 15 s, so
 * 45 s without a byte means the link is dead and the connection is restarted. Callbacks arrive on
 * the worker thread; UI code must post to the main thread.
 */
public final class SseClient {

    public enum State { CONNECTING, LIVE, RECONNECTING }

    public interface Listener {
        void onState(State state, String message);

        void onEvent(String name, JSONObject data);
    }

    static final int SILENCE_TIMEOUT_MS = 45_000;
    static final long MAX_BACKOFF_MS = 30_000;

    private final ApiClient api;
    private final Listener listener;
    private volatile boolean stopped;
    private volatile HttpURLConnection current;
    private Thread thread;

    public SseClient(ApiClient api, Listener listener) {
        this.api = api;
        this.listener = listener;
    }

    public synchronized void start() {
        if (thread != null) {
            return;
        }
        stopped = false;
        thread = new Thread(this::run, "mobilityops-sse");
        thread.setDaemon(true);
        thread.start();
    }

    public synchronized void stop() {
        stopped = true;
        HttpURLConnection c = current;
        if (c != null) {
            c.disconnect(); // unblocks a read in progress
        }
        if (thread != null) {
            thread.interrupt();
            thread = null;
        }
    }

    /** Exponential backoff: 1 s, 2 s, 4 s ... capped at 30 s. */
    static long backoff(int failures) {
        long ms = 1_000L << Math.min(Math.max(failures, 0), 5);
        return Math.min(ms, MAX_BACKOFF_MS);
    }

    private void run() {
        int failures = 0;
        boolean first = true;
        while (!stopped) {
            listener.onState(first ? State.CONNECTING : State.RECONNECTING, null);
            first = false;
            String problem;
            try {
                boolean gotData = readOnce();
                failures = gotData ? 0 : failures + 1;
                problem = "The connection closed.";
            } catch (ApiException e) {
                failures++;
                problem = e.getMessage();
            } catch (IOException e) {
                failures++;
                problem = e.getMessage() == null ? "Connection problem." : e.getMessage();
            }
            if (stopped) {
                return;
            }
            listener.onState(State.RECONNECTING, problem);
            try {
                Thread.sleep(backoff(failures));
            } catch (InterruptedException e) {
                return;
            }
        }
    }

    /** One connection. Returns whether at least one event arrived. */
    private boolean readOnce() throws IOException {
        HttpURLConnection conn = api.open("/api/v1/live/stream", null);
        current = conn;
        boolean gotData = false;
        try {
            conn.setRequestProperty("Accept", "text/event-stream");
            conn.setReadTimeout(SILENCE_TIMEOUT_MS);
            int status = conn.getResponseCode();
            if (status >= 400) {
                InputStream err = conn.getErrorStream();
                String body = "";
                if (err != null) {
                    try (Reader r = new InputStreamReader(err, StandardCharsets.UTF_8)) {
                        StringBuilder sb = new StringBuilder();
                        char[] buf = new char[1024];
                        int n;
                        while ((n = r.read(buf)) != -1 && sb.length() < 4096) {
                            sb.append(buf, 0, n);
                        }
                        body = sb.toString();
                    }
                }
                throw ApiClient.toException(status, body);
            }
            SseParser parser = new SseParser();
            try (Reader reader = new InputStreamReader(conn.getInputStream(), StandardCharsets.UTF_8)) {
                char[] buf = new char[4096];
                int n;
                while (!stopped && (n = reader.read(buf)) != -1) {
                    for (SseParser.Event ev : parser.feed(new String(buf, 0, n))) {
                        try {
                            JSONObject body = new JSONObject(ev.data);
                            if ("hello".equals(ev.name)) {
                                listener.onState(State.LIVE, null);
                            }
                            gotData = true;
                            listener.onEvent(ev.name, body);
                        } catch (JSONException ignored) {
                            // a malformed event must not end the stream
                        }
                    }
                }
            }
            return gotData;
        } finally {
            current = null;
            conn.disconnect();
        }
    }
}
