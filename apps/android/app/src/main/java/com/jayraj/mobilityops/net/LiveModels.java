package com.jayraj.mobilityops.net;

import java.util.ArrayList;
import java.util.List;

import org.json.JSONArray;
import org.json.JSONObject;

/** Plain objects for the messages on the live stream, parsed from JSON. Missing values stay null. */
public final class LiveModels {
    private LiveModels() {}

    public static final class ZoneRow {
        public final String zone;
        public final double actual;
        public final double forecast;

        ZoneRow(String zone, double actual, double forecast) {
            this.zone = zone;
            this.actual = actual;
            this.forecast = forecast;
        }
    }

    public static final class AnomalyRow {
        public final String zone;
        public final String direction;
        public final String severity;
        public final String scope;

        AnomalyRow(String zone, String direction, String severity, String scope) {
            this.zone = zone;
            this.direction = direction;
            this.severity = severity;
            this.scope = scope;
        }
    }

    public static final class ReplayTick {
        public final int index;
        public final int of;
        public final int loop;
        public final String hourTs;
        public final double actual;
        public final double forecast;
        public final double baseline;
        public final double absError;
        public final Double runningWape;
        public final String label;
        public final List<ZoneRow> topZones;
        public final List<AnomalyRow> anomalies;

        ReplayTick(JSONObject o) {
            index = o.optInt("index");
            of = o.optInt("of");
            loop = o.optInt("loop");
            hourTs = o.optString("hour_ts", "");
            actual = o.optDouble("actual", 0);
            forecast = o.optDouble("forecast", 0);
            baseline = o.optDouble("baseline", 0);
            absError = o.optDouble("abs_error", 0);
            runningWape = o.isNull("running_wape") ? null : o.optDouble("running_wape");
            label = o.optString("label", "");
            topZones = new ArrayList<>();
            JSONArray z = o.optJSONArray("top_zones");
            for (int i = 0; z != null && i < z.length(); i++) {
                JSONObject r = z.optJSONObject(i);
                if (r != null) {
                    topZones.add(new ZoneRow(r.optString("zone"), r.optDouble("actual"), r.optDouble("forecast")));
                }
            }
            anomalies = new ArrayList<>();
            JSONArray a = o.optJSONArray("anomalies");
            for (int i = 0; a != null && i < a.length(); i++) {
                JSONObject r = a.optJSONObject(i);
                if (r != null) {
                    anomalies.add(new AnomalyRow(r.optString("zone"), r.optString("direction"),
                            r.optString("severity"), r.optString("scope")));
                }
            }
        }
    }

    public static ReplayTick tick(JSONObject o) {
        return new ReplayTick(o);
    }

    public static final class Station {
        public final String name;
        public final int capacity;

        Station(String name, int capacity) {
            this.name = name;
            this.capacity = capacity;
        }
    }

    public static final class Citibike {
        public final int active;
        public final int offline;
        public final int bikes;
        public final int ebikes;
        public final int docks;
        public final int empty;
        public final int full;
        public final List<Station> largestEmpty;
        public final List<Station> largestFull;

        Citibike(JSONObject d) {
            active = d.optInt("active");
            offline = d.optInt("offline");
            bikes = d.optInt("bikes");
            ebikes = d.optInt("ebikes");
            docks = d.optInt("docks");
            empty = d.optInt("empty");
            full = d.optInt("full");
            largestEmpty = stations(d.optJSONArray("largest_empty"));
            largestFull = stations(d.optJSONArray("largest_full"));
        }

        private static List<Station> stations(JSONArray a) {
            List<Station> out = new ArrayList<>();
            for (int i = 0; a != null && i < a.length(); i++) {
                JSONObject r = a.optJSONObject(i);
                if (r != null) {
                    out.add(new Station(r.optString("name"), r.optInt("capacity")));
                }
            }
            return out;
        }
    }

    public static final class Weather {
        public final String description;
        public final Double temperatureC;
        public final Double windKmh;
        public final Double humidityPct;
        public final Double rainMm;

        Weather(JSONObject d) {
            description = d.isNull("description") ? null : d.optString("description");
            temperatureC = number(d, "temperature_c");
            windKmh = number(d, "wind_kmh");
            humidityPct = number(d, "humidity_pct");
            rainMm = number(d, "precipitation_last_hour_mm");
        }

        private static Double number(JSONObject d, String key) {
            return d.isNull(key) || !d.has(key) ? null : d.optDouble(key);
        }
    }

    /** A feed message: status, provenance and (when present) the last good data. */
    public static final class Feed {
        public final String name;
        public final String status;
        public final String source;
        public final String asOf;
        public final String error;
        public final Citibike citibike;
        public final Weather weather;

        Feed(JSONObject o) {
            name = o.optString("feed");
            status = o.optString("status", "starting");
            source = o.optString("source", "");
            asOf = o.isNull("as_of") ? null : o.optString("as_of");
            error = o.isNull("error") ? null : o.optString("error");
            JSONObject data = o.optJSONObject("data");
            citibike = data != null && "citibike".equals(name) ? new Citibike(data) : null;
            weather = data != null && "weather".equals(name) ? new Weather(data) : null;
        }

        public boolean isDown() {
            return "unavailable".equals(status);
        }
    }

    public static Feed feed(JSONObject o) {
        return new Feed(o);
    }

    /** (time, bikes, docks) points for the availability chart. */
    public static final class HistoryPoint {
        public final String ts;
        public final int bikes;
        public final int docks;

        HistoryPoint(String ts, int bikes, int docks) {
            this.ts = ts;
            this.bikes = bikes;
            this.docks = docks;
        }
    }

    public static List<HistoryPoint> history(JSONArray a) {
        List<HistoryPoint> out = new ArrayList<>();
        for (int i = 0; a != null && i < a.length(); i++) {
            JSONObject r = a.optJSONObject(i);
            if (r != null) {
                out.add(new HistoryPoint(r.optString("ts"), r.optInt("bikes"), r.optInt("docks")));
            }
        }
        return out;
    }
}
