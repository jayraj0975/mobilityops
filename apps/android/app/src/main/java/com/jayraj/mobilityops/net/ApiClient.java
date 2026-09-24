package com.jayraj.mobilityops.net;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Map;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Minimal JSON-over-HTTP client for the MobilityOps API (platform classes only). */
public final class ApiClient {
    private static final int CONNECT_TIMEOUT_MS = 8_000;
    private static final int READ_TIMEOUT_MS = 30_000;
    private static final int MAX_BYTES = 8 * 1024 * 1024;

    private final String baseUrl;
    private final String apiKey;

    public ApiClient(String baseUrl, String apiKey) {
        this.baseUrl = baseUrl;
        this.apiKey = apiKey == null ? "" : apiKey;
    }

    public JSONObject getObject(String path, Map<String, String> query) throws IOException {
        try {
            return new JSONObject(get(path, query));
        } catch (JSONException e) {
            throw new IOException("The server sent something that is not JSON.", e);
        }
    }

    public JSONArray getArray(String path, Map<String, String> query) throws IOException {
        try {
            return new JSONArray(get(path, query));
        } catch (JSONException e) {
            throw new IOException("The server sent something that is not JSON.", e);
        }
    }

    public String get(String path, Map<String, String> query) throws IOException {
        HttpURLConnection conn = open(path, query);
        try {
            int status = conn.getResponseCode();
            InputStream stream = status >= 400 ? conn.getErrorStream() : conn.getInputStream();
            String body = stream == null ? "" : read(stream);
            if (status >= 400) {
                throw toException(status, body);
            }
            return body;
        } finally {
            conn.disconnect();
        }
    }

    /** The connection used by both JSON requests and the event stream. */
    HttpURLConnection open(String path, Map<String, String> query) throws IOException {
        HttpURLConnection conn = (HttpURLConnection) new URL(baseUrl + path + queryString(query)).openConnection();
        conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
        conn.setReadTimeout(READ_TIMEOUT_MS);
        conn.setRequestProperty("Accept", "application/json");
        if (!apiKey.isEmpty()) {
            conn.setRequestProperty("X-API-Key", apiKey);
        }
        return conn;
    }

    static String queryString(Map<String, String> query) throws IOException {
        if (query == null || query.isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder("?");
        for (Map.Entry<String, String> e : query.entrySet()) {
            if (sb.length() > 1) {
                sb.append('&');
            }
            sb.append(URLEncoder.encode(e.getKey(), "UTF-8")).append('=').append(URLEncoder.encode(e.getValue(), "UTF-8"));
        }
        return sb.toString();
    }

    /** Turn an error response into an exception carrying the server's message if it has one. */
    static ApiException toException(int status, String body) {
        String code = "http_error";
        String message = "The server answered HTTP " + status + ".";
        try {
            JSONObject error = new JSONObject(body).optJSONObject("error");
            if (error != null) {
                code = error.optString("code", code);
                message = error.optString("message", message);
            }
        } catch (JSONException ignored) {
            // not our error shape (a proxy page, for instance): keep the generic message
        }
        if (status == 401 || status == 403) {
            message = "The server refused the API key (HTTP " + status + "). Check it in Settings.";
        }
        return new ApiException(status, code, message);
    }

    private static String read(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) != -1) {
            out.write(buf, 0, n);
            if (out.size() > MAX_BYTES) {
                throw new IOException("The response was larger than " + MAX_BYTES + " bytes.");
            }
        }
        return out.toString(StandardCharsets.UTF_8.name());
    }
}
