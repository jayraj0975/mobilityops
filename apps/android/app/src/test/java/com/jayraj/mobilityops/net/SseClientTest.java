package com.jayraj.mobilityops.net;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;

/** The real client against a real local server speaking server-sent events over a socket. */
public class SseClientTest {
    private FakeServer server;
    private final AtomicInteger connections = new AtomicInteger();
    private final List<String> apiKeys = new CopyOnWriteArrayList<>();

    @After
    public void stop() throws IOException {
        if (server != null) {
            server.close();
        }
    }

    private static class Recorder implements SseClient.Listener {
        final List<String> names = new CopyOnWriteArrayList<>();
        final List<SseClient.State> states = new CopyOnWriteArrayList<>();
        final List<String> messages = new CopyOnWriteArrayList<>();
        final CountDownLatch latch;
        final String until;

        Recorder(int count, String until) {
            this.latch = new CountDownLatch(count);
            this.until = until;
        }

        @Override
        public void onState(SseClient.State state, String message) {
            states.add(state);
            if (message != null) {
                messages.add(message);
                if (until != null && message.contains(until)) {
                    latch.countDown();
                }
            }
        }

        @Override
        public void onEvent(String name, JSONObject data) {
            names.add(name);
            if (until == null) {
                latch.countDown();
            }
        }
    }

    @Test
    public void deliversEventsInOrderAndSendsTheApiKeyAsAHeader() throws Exception {
        server = new FakeServer((headers, out) -> {
            apiKeys.add(String.valueOf(headers.get("x-api-key")));
            FakeServer.streamHead(out);
            FakeServer.write(out, "event: hello\ndata: {\"kind\":\"hello\"}\n\n");
            FakeServer.write(out, ": keep-alive\n\n");
            FakeServer.write(out, "event: replay\ndata: {\"index\":1}\n\nevent: fe");
            FakeServer.write(out, "ed\ndata: {\"feed\":\"citibike\"}\n\n");
            Thread.sleep(300);
        });
        Recorder r = new Recorder(3, null);
        SseClient client = new SseClient(new ApiClient(server.baseUrl(), "secret-key"), r);
        client.start();
        assertTrue(r.latch.await(5, TimeUnit.SECONDS));
        client.stop();
        assertEquals(List.of("hello", "replay", "feed"), r.names.subList(0, 3));
        assertEquals("secret-key", apiKeys.get(0));
        assertTrue(r.states.contains(SseClient.State.LIVE));
    }

    @Test
    public void reconnectsAfterTheServerDropsTheConnection() throws Exception {
        server = new FakeServer((headers, out) -> {
            int n = connections.incrementAndGet();
            FakeServer.streamHead(out);
            FakeServer.write(out, "event: hello\ndata: {\"connection\":" + n + "}\n\n");
        });
        Recorder r = new Recorder(2, null); // two hellos = one reconnect
        SseClient client = new SseClient(new ApiClient(server.baseUrl(), ""), r);
        client.start();
        assertTrue("should reconnect within the 1 s backoff", r.latch.await(8, TimeUnit.SECONDS));
        client.stop();
        assertTrue(connections.get() >= 2);
        assertTrue(r.states.contains(SseClient.State.RECONNECTING));
    }

    @Test
    public void aRefusedStreamReportsTheServersOwnReason() throws Exception {
        server = new FakeServer((headers, out) -> {
            String body = "{\"error\":{\"code\":\"busy\",\"message\":\"32 live streams are already open\",\"request_id\":\"x\"}}";
            int length = body.getBytes(StandardCharsets.UTF_8).length;
            FakeServer.write(out, "HTTP/1.1 429 Too Many Requests\r\nContent-Type: application/json\r\nContent-Length: "
                    + length + "\r\nConnection: close\r\n\r\n" + body);
        });
        Recorder r = new Recorder(1, "32 live streams are already open");
        SseClient client = new SseClient(new ApiClient(server.baseUrl(), ""), r);
        client.start();
        assertTrue(r.latch.await(6, TimeUnit.SECONDS));
        client.stop();
        assertTrue(r.names.isEmpty());
    }

    @Test
    public void aMalformedEventDoesNotEndTheStream() throws Exception {
        server = new FakeServer((headers, out) -> {
            FakeServer.streamHead(out);
            FakeServer.write(out, "event: replay\ndata: not json\n\n");
            FakeServer.write(out, "event: replay\ndata: {\"index\":2}\n\n");
            Thread.sleep(300);
        });
        Recorder r = new Recorder(1, null);
        SseClient client = new SseClient(new ApiClient(server.baseUrl(), ""), r);
        client.start();
        assertTrue(r.latch.await(5, TimeUnit.SECONDS));
        client.stop();
        assertEquals(List.of("replay"), r.names.subList(0, 1));
    }

    @Test
    public void backoffDoublesFromOneSecondAndStopsAtThirty() {
        assertEquals(1_000, SseClient.backoff(0));
        assertEquals(2_000, SseClient.backoff(1));
        assertEquals(4_000, SseClient.backoff(2));
        assertEquals(16_000, SseClient.backoff(4));
        assertEquals(30_000, SseClient.backoff(5));
        assertEquals(30_000, SseClient.backoff(50));
        assertEquals(1_000, SseClient.backoff(-3));
    }
}
