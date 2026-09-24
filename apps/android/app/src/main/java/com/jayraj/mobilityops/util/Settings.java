package com.jayraj.mobilityops.util;

import android.content.Context;
import android.content.SharedPreferences;

/** Where the server is and how to authenticate. Stored in private app preferences. */
public final class Settings {
    /** 10.0.2.2 is the host machine as seen from the Android emulator. */
    public static final String DEFAULT_URL = "http://10.0.2.2:8000";

    private static final String FILE = "mobilityops";
    private static final String KEY_URL = "server_url";
    private static final String KEY_API_KEY = "api_key";

    private final SharedPreferences prefs;

    public Settings(Context context) {
        this.prefs = context.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    public String serverUrl() {
        return normalizeUrl(prefs.getString(KEY_URL, DEFAULT_URL));
    }

    public String apiKey() {
        return prefs.getString(KEY_API_KEY, "");
    }

    public boolean isConfigured() {
        return prefs.contains(KEY_URL);
    }

    public void save(String url, String apiKey) {
        prefs.edit().putString(KEY_URL, normalizeUrl(url)).putString(KEY_API_KEY, apiKey.trim()).apply();
    }

    /** Trim, add a scheme if missing and drop trailing slashes: "host:8000/" becomes "http://host:8000". */
    public static String normalizeUrl(String raw) {
        String url = raw == null ? "" : raw.trim();
        if (url.isEmpty()) {
            return DEFAULT_URL;
        }
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "http://" + url;
        }
        while (url.endsWith("/")) {
            url = url.substring(0, url.length() - 1);
        }
        return url;
    }
}
