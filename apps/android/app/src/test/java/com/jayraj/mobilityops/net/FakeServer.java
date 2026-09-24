package com.jayraj.mobilityops.net;

import java.io.BufferedReader;
import java.io.Closeable;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/** A minimal HTTP server for tests: reads the request head, then lets the test write the raw response. */
final class FakeServer implements Closeable {

    interface Handler {
        void handle(Map<String, String> headers, OutputStream out) throws Exception;
    }

    private final ServerSocket socket;
    private final Handler handler;

    FakeServer(Handler handler) throws IOException {
        this.handler = handler;
        this.socket = new ServerSocket(0, 10, InetAddress.getByName("127.0.0.1"));
        Thread acceptor = new Thread(this::accept, "fake-server");
        acceptor.setDaemon(true);
        acceptor.start();
    }

    String baseUrl() {
        return "http://127.0.0.1:" + socket.getLocalPort();
    }

    private void accept() {
        while (!socket.isClosed()) {
            try {
                Socket client = socket.accept();
                Thread t = new Thread(() -> serve(client));
                t.setDaemon(true);
                t.start();
            } catch (IOException e) {
                return;
            }
        }
    }

    private void serve(Socket client) {
        try (Socket c = client) {
            BufferedReader in = new BufferedReader(new InputStreamReader(c.getInputStream(), StandardCharsets.UTF_8));
            Map<String, String> headers = new HashMap<>();
            String line = in.readLine(); // request line
            while (line != null && !(line = in.readLine()).isEmpty()) {
                int i = line.indexOf(':');
                if (i > 0) {
                    headers.put(line.substring(0, i).trim().toLowerCase(), line.substring(i + 1).trim());
                }
            }
            handler.handle(headers, c.getOutputStream());
        } catch (Exception ignored) {
            // the client hung up, or the test is over
        }
    }

    static void write(OutputStream out, String text) throws IOException {
        out.write(text.getBytes(StandardCharsets.UTF_8));
        out.flush();
    }

    /** Status line and headers of a streamed (close-delimited) event-stream response. */
    static void streamHead(OutputStream out) throws IOException {
        write(out, "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n");
    }

    @Override
    public void close() throws IOException {
        socket.close();
    }
}
