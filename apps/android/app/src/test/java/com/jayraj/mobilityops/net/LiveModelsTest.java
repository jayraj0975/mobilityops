package com.jayraj.mobilityops.net;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Test;

public class LiveModelsTest {

    @Test
    public void parsesAReplayTickWithZonesAndAnomalies() throws Exception {
        JSONObject o = new JSONObject("{\"kind\":\"replay\",\"index\":12,\"of\":1344,\"loop\":0,"
                + "\"hour_ts\":\"2024-11-06T12:00:00\",\"actual\":6000.0,\"forecast\":5900.5,\"baseline\":5500,"
                + "\"abs_error\":99.5,\"running_wape\":0.031,\"label\":\"REPLAY ...\","
                + "\"top_zones\":[{\"location_id\":132,\"zone\":\"JFK Airport\",\"actual\":120,\"forecast\":110}],"
                + "\"anomalies\":[{\"zone\":\"Midtown\",\"direction\":\"surge\",\"severity\":\"high\",\"scope\":\"localised\"}]}");
        LiveModels.ReplayTick t = LiveModels.tick(o);
        assertEquals(12, t.index);
        assertEquals(1344, t.of);
        assertEquals(5900.5, t.forecast, 1e-9);
        assertEquals(0.031, t.runningWape, 1e-9);
        assertEquals("JFK Airport", t.topZones.get(0).zone);
        assertEquals("Midtown", t.anomalies.get(0).zone);
    }

    @Test
    public void aNullRunningAccuracyStaysNullInsteadOfBecomingZero() throws Exception {
        LiveModels.ReplayTick t = LiveModels.tick(new JSONObject("{\"index\":0,\"running_wape\":null}"));
        assertNull(t.runningWape);
    }

    @Test
    public void parsesACitibikeFeedAndItsFreshnessFields() throws Exception {
        JSONObject o = new JSONObject("{\"kind\":\"feed\",\"feed\":\"citibike\",\"status\":\"ok\",\"source\":\"GBFS\","
                + "\"as_of\":\"2026-09-24T13:09:54+00:00\",\"error\":null,\"data\":{\"stations\":10,\"active\":8,\"offline\":2,"
                + "\"bikes\":40,\"ebikes\":12,\"docks\":33,\"empty\":1,\"full\":2,"
                + "\"largest_empty\":[{\"name\":\"Alpha St\",\"capacity\":30}],\"largest_full\":[]}}");
        LiveModels.Feed f = LiveModels.feed(o);
        assertFalse(f.isDown());
        assertEquals("2026-09-24T13:09:54+00:00", f.asOf);
        assertNull(f.error);
        assertNotNull(f.citibike);
        assertEquals(40, f.citibike.bikes);
        assertEquals("Alpha St", f.citibike.largestEmpty.get(0).name);
        assertTrue(f.citibike.largestFull.isEmpty());
        assertNull(f.weather);
    }

    @Test
    public void aDownFeedKeepsItsLastGoodDataAndItsError() throws Exception {
        JSONObject o = new JSONObject("{\"feed\":\"citibike\",\"status\":\"unavailable\",\"error\":\"HTTPStatusError: 503\","
                + "\"data\":{\"bikes\":7}}");
        LiveModels.Feed f = LiveModels.feed(o);
        assertTrue(f.isDown());
        assertEquals("HTTPStatusError: 503", f.error);
        assertEquals(7, f.citibike.bikes);
    }

    @Test
    public void weatherReadingsThatAreMissingStayNull() throws Exception {
        JSONObject o = new JSONObject("{\"feed\":\"weather\",\"status\":\"ok\",\"data\":{\"description\":null,"
                + "\"temperature_c\":21.7,\"wind_kmh\":null,\"humidity_pct\":63.2,\"precipitation_last_hour_mm\":null}}");
        LiveModels.Weather w = LiveModels.feed(o).weather;
        assertEquals(21.7, w.temperatureC, 1e-9);
        assertNull(w.windKmh);
        assertNull(w.rainMm);
        assertNull(w.description);
    }

    @Test
    public void aFeedWithNoDataYetIsHandled() throws Exception {
        LiveModels.Feed f = LiveModels.feed(new JSONObject("{\"feed\":\"weather\",\"status\":\"starting\",\"data\":null}"));
        assertNull(f.weather);
        assertNull(f.citibike);
    }

    @Test
    public void historyPointsAreParsedInOrder() throws Exception {
        java.util.List<LiveModels.HistoryPoint> h = LiveModels.history(new org.json.JSONArray(
                "[{\"ts\":\"2026-09-24T13:00:00+00:00\",\"bikes\":10,\"docks\":5},{\"ts\":\"2026-09-24T13:01:00+00:00\",\"bikes\":11,\"docks\":4}]"));
        assertEquals(2, h.size());
        assertEquals(11, h.get(1).bikes);
    }
}
