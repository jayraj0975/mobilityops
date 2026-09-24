package com.jayraj.mobilityops.net;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.LinkedHashMap;
import java.util.Map;

import org.junit.Test;

public class ApiClientTest {

    @Test
    public void errorBodiesKeepTheServersMessageAndCode() throws Exception {
        ApiException e = ApiClient.toException(404, "{\"error\":{\"code\":\"no_data\",\"message\":\"no data for that period\",\"request_id\":\"r\"}}");
        assertEquals(404, e.status);
        assertEquals("no_data", e.code);
        assertEquals("no data for that period", e.getMessage());
        assertTrue(e.isNotReady());
    }

    @Test
    public void anUnknownErrorBodyGetsAGenericMessage() {
        ApiException e = ApiClient.toException(502, "<html>Bad gateway</html>");
        assertEquals("http_error", e.code);
        assertTrue(e.getMessage().contains("502"));
        assertFalse(e.isNotReady());
    }

    @Test
    public void authFailuresPointAtTheApiKeySetting() {
        assertTrue(ApiClient.toException(401, "").getMessage().contains("API key"));
        assertTrue(ApiClient.toException(403, "{}").getMessage().contains("Settings"));
    }

    @Test
    public void queryStringsAreEncodedAndOrdered() throws Exception {
        Map<String, String> q = new LinkedHashMap<>();
        q.put("start", "2024-11-01");
        q.put("zone", "Times Sq/Theatre District");
        assertEquals("?start=2024-11-01&zone=Times+Sq%2FTheatre+District", ApiClient.queryString(q));
        assertEquals("", ApiClient.queryString(null));
        assertEquals("", ApiClient.queryString(new LinkedHashMap<>()));
    }
}
