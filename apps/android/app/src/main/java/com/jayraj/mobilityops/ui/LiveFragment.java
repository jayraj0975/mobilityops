package com.jayraj.mobilityops.ui;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.LinearLayout;

import androidx.annotation.NonNull;
import androidx.core.content.ContextCompat;

import com.jayraj.mobilityops.R;
import com.jayraj.mobilityops.net.LiveModels;
import com.jayraj.mobilityops.net.SseClient;
import com.jayraj.mobilityops.util.Async;
import com.jayraj.mobilityops.util.Fmt;
import com.jayraj.mobilityops.util.Times;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * The real-time screen. Two clearly different things are shown: a REPLAY of held-out taxi days (no
 * live taxi feed exists) and genuinely LIVE public feeds (Citi Bike, weather). The stream runs only
 * while the screen is visible.
 */
public final class LiveFragment extends ScreenFragment {
    private static final int MAX_TICKS = 96;

    private final List<LiveModels.ReplayTick> ticks = new ArrayList<>();
    private LiveModels.Feed citibike;
    private LiveModels.Feed weather;
    private List<LiveModels.HistoryPoint> history = new ArrayList<>();
    private boolean replayAvailable = true;
    private String replayReason = "";
    private String replayLabel = "";
    private double secondsPerHour = 2;
    private boolean feedsEnabled = true;
    private SseClient.State state = SseClient.State.CONNECTING;
    private String stateMessage;
    private SseClient client;
    private final Handler clock = new Handler(Looper.getMainLooper());
    private final Runnable tickAge = new Runnable() {
        @Override
        public void run() {
            if (content != null) {
                render();
                clock.postDelayed(this, 5_000);
            }
        }
    };

    @Override
    protected void build(@NonNull Context context) {
        render();
    }

    @Override
    public void onStart() {
        super.onStart();
        client = new SseClient(api(), new SseClient.Listener() {
            @Override
            public void onState(SseClient.State s, String message) {
                Async.onMain(() -> {
                    state = s;
                    stateMessage = message;
                    render();
                });
            }

            @Override
            public void onEvent(String name, JSONObject data) {
                Async.onMain(() -> handle(name, data));
            }
        });
        client.start();
        clock.postDelayed(tickAge, 5_000);
    }

    @Override
    public void onStop() {
        clock.removeCallbacks(tickAge);
        if (client != null) {
            client.stop();
            client = null;
        }
        super.onStop();
    }

    private void handle(String name, JSONObject d) {
        switch (name) {
            case "hello":
                JSONObject replay = d.optJSONObject("replay");
                ticks.clear();
                if (replay != null) {
                    replayAvailable = replay.optBoolean("available", false);
                    replayReason = replay.optString("reason", "");
                    replayLabel = replay.optString("label", "");
                    secondsPerHour = replay.optDouble("seconds_per_hour", 2);
                    JSONArray h = replay.optJSONArray("history");
                    for (int i = 0; h != null && i < h.length(); i++) {
                        JSONObject t = h.optJSONObject(i);
                        if (t != null) {
                            ticks.add(LiveModels.tick(t));
                        }
                    }
                }
                JSONObject feeds = d.optJSONObject("feeds");
                feedsEnabled = feeds == null || feeds.optBoolean("enabled", true);
                if (feeds != null) {
                    JSONObject cb = feeds.optJSONObject("citibike");
                    JSONObject wx = feeds.optJSONObject("weather");
                    citibike = cb == null ? null : LiveModels.feed(cb);
                    weather = wx == null ? null : LiveModels.feed(wx);
                    history = LiveModels.history(feeds.optJSONArray("history"));
                }
                break;
            case "replay":
                LiveModels.ReplayTick t = LiveModels.tick(d);
                if (!ticks.isEmpty() && t.index < ticks.get(ticks.size() - 1).index) {
                    ticks.clear(); // the replay wrapped around to its start
                }
                ticks.removeIf(x -> x.index == t.index);
                ticks.add(t);
                while (ticks.size() > MAX_TICKS) {
                    ticks.remove(0);
                }
                break;
            case "feed":
                LiveModels.Feed f = LiveModels.feed(d);
                if ("citibike".equals(f.name)) {
                    citibike = f;
                } else {
                    weather = f;
                }
                break;
            case "history":
                history = LiveModels.history(d.optJSONArray("citibike"));
                break;
            default:
                return;
        }
        render();
    }

    private void render() {
        if (content == null) {
            return;
        }
        Context c = requireContext();
        content.removeAllViews();

        String status;
        switch (state) {
            case LIVE:
                status = "Connected: receiving live updates";
                break;
            case RECONNECTING:
                status = "Connection lost: reconnecting…" + (stateMessage == null ? "" : " (" + stateMessage + ")");
                break;
            default:
                status = "Connecting to the live stream…";
        }
        content.addView(Ui.text(c, status, 14, state == SseClient.State.LIVE ? R.color.muted : R.color.warn, true));

        content.addView(Ui.heading(c, "Taxi demand: replay of held-out days"));
        content.addView(Ui.banner(c, "REPLAY, NOT LIVE.",
                "NYC taxi trips are published monthly, so no live taxi feed exists. This advances through days the model "
                        + "had not seen when it forecast them, one hour every " + Fmt.number(secondsPerHour, 1)
                        + " seconds, on a clock shared by every viewer.",
                R.color.replay_bg, R.color.replay_border));
        if (!replayAvailable) {
            content.addView(Ui.body(c, "The replay is not available yet: " + replayReason));
        } else if (ticks.isEmpty()) {
            content.addView(Ui.muted(c, "Waiting for the next replay hour…"));
        } else {
            renderReplay(c);
        }

        content.addView(Ui.heading(c, "Live city feeds"));
        content.addView(Ui.banner(c, "LIVE.",
                "Real public data, fetched while someone is watching: Citi Bike station availability and the current "
                        + "weather in Central Park.",
                R.color.live_bg, R.color.live_border));
        if (!feedsEnabled) {
            content.addView(Ui.body(c, "Live feeds are switched off on this server (MOBILITYOPS_LIVE_FEEDS=false)."));
        } else {
            renderCitibike(c);
            renderWeather(c);
        }
    }

    private void renderReplay(Context c) {
        LiveModels.ReplayTick last = ticks.get(ticks.size() - 1);
        Double errPct = last.actual > 0 ? last.absError / last.actual : null;
        content.addView(Ui.kpiGrid(c, Arrays.asList(
                new String[] {"Replay hour (New York time)", Fmt.hour(last.hourTs),
                        "hour " + (last.index + 1) + " of " + last.of + (last.loop > 0 ? ", loop " + (last.loop + 1) : "")},
                new String[] {"Actual pickups this hour", Fmt.integer(last.actual), null},
                new String[] {"Forecast made beforehand", Fmt.integer(last.forecast),
                        errPct == null ? null : "off by " + Fmt.percent(errPct, 1)},
                new String[] {"City-total error so far (WAPE)", Fmt.percent(last.runningWape, 1),
                        "hourly totals over all zones; easier than one zone"})));

        double[] actual = new double[ticks.size()];
        double[] forecast = new double[ticks.size()];
        double[] baseline = new double[ticks.size()];
        String[] labels = new String[ticks.size()];
        for (int i = 0; i < ticks.size(); i++) {
            actual[i] = ticks.get(i).actual;
            forecast[i] = ticks.get(i).forecast;
            baseline[i] = ticks.get(i).baseline;
            labels[i] = Fmt.hour(ticks.get(i).hourTs).substring(5);
        }
        LineChartView chart = Ui.chart(c);
        chart.setData(labels, Arrays.asList(
                new LineChartView.Series("Actual", ContextCompat.getColor(c, R.color.series1), actual, false),
                new LineChartView.Series("Forecast", ContextCompat.getColor(c, R.color.series2), forecast, false),
                new LineChartView.Series("4-week mean", ContextCompat.getColor(c, R.color.series3), baseline, true)),
                "City pickups per hour, actual against the forecast. Latest hour: actual " + Fmt.integer(last.actual)
                        + ", forecast " + Fmt.integer(last.forecast) + ".");
        content.addView(chart);
        content.addView(Ui.muted(c, replayLabel));

        content.addView(Ui.subheading(c, "Busiest zones this hour"));
        List<String[]> rows = new ArrayList<>();
        for (LiveModels.ZoneRow z : last.topZones) {
            rows.add(new String[] {z.zone, Fmt.integer(z.actual), Fmt.integer(z.forecast)});
        }
        content.addView(Ui.table(c, new String[] {"Zone", "Actual", "Forecast"}, rows, new boolean[] {false, true, true}));

        content.addView(Ui.subheading(c, "Anomaly events covering this hour"));
        if (last.anomalies.isEmpty()) {
            content.addView(Ui.muted(c, "None. Events describe what coincided with a deviation; they never assert a cause."));
        }
        for (LiveModels.AnomalyRow a : last.anomalies) {
            content.addView(Ui.body(c, a.zone + ": " + a.direction + ", " + a.severity + " severity (" + a.scope + ")."));
        }
    }

    private void renderFeedNotice(Context c, LiveModels.Feed feed, boolean hasData) {
        if (feed == null || "starting".equals(feed.status)) {
            content.addView(Ui.muted(c, "Waiting for the first reading…"));
            return;
        }
        if (feed.isDown()) {
            content.addView(Ui.banner(c, "The source is not answering right now",
                    "(" + feed.error + ") " + (hasData ? "The figures below are the last good reading, not current."
                            : "No reading has been received yet."),
                    R.color.surface, R.color.fail));
        }
        long age = Times.ageSeconds(feed.asOf, System.currentTimeMillis());
        content.addView(Ui.muted(c, "Source: " + feed.source + ". Reading "
                + (age < 0 ? "from an unknown time" : Fmt.age(age)) + "."));
    }

    private void renderCitibike(Context c) {
        content.addView(Ui.subheading(c, "Citi Bike availability"));
        LiveModels.Citibike d = citibike == null ? null : citibike.citibike;
        renderFeedNotice(c, citibike, d != null);
        if (d == null) {
            return;
        }
        content.addView(Ui.kpiGrid(c, Arrays.asList(
                new String[] {"Bikes available", Fmt.integer(d.bikes), Fmt.integer(d.ebikes) + " of them e-bikes"},
                new String[] {"Free docks", Fmt.integer(d.docks), null},
                new String[] {"Empty stations", Fmt.integer(d.empty), "of " + Fmt.integer(d.active) + " in service"},
                new String[] {"Full stations", Fmt.integer(d.full),
                        d.offline > 0 ? Fmt.integer(d.offline) + " stations offline" : null})));
        if (history.size() > 1) {
            double[] bikes = new double[history.size()];
            double[] docks = new double[history.size()];
            String[] labels = new String[history.size()];
            for (int i = 0; i < history.size(); i++) {
                bikes[i] = history.get(i).bikes;
                docks[i] = history.get(i).docks;
                String ts = history.get(i).ts;
                labels[i] = ts != null && ts.length() >= 16 ? ts.substring(11, 16) : "";
            }
            LineChartView chart = Ui.chart(c);
            chart.setData(labels, Arrays.asList(
                    new LineChartView.Series("Bikes", ContextCompat.getColor(c, R.color.series1), bikes, false),
                    new LineChartView.Series("Free docks", ContextCompat.getColor(c, R.color.series2), docks, false)),
                    "Bikes and docks available since this server started watching.");
            content.addView(chart);
        }
        content.addView(Ui.subheading(c, "Largest empty stations"));
        content.addView(stationTable(c, d.largestEmpty));
        content.addView(Ui.subheading(c, "Largest full stations"));
        content.addView(stationTable(c, d.largestFull));
    }

    private View stationTable(Context c, List<LiveModels.Station> stations) {
        if (stations.isEmpty()) {
            return Ui.muted(c, "None right now.");
        }
        List<String[]> rows = new ArrayList<>();
        for (LiveModels.Station s : stations) {
            rows.add(new String[] {s.name, Fmt.integer(s.capacity)});
        }
        return Ui.table(c, new String[] {"Station", "Docks"}, rows, new boolean[] {false, true});
    }

    private void renderWeather(Context c) {
        content.addView(Ui.subheading(c, "Weather in Central Park"));
        LiveModels.Weather w = weather == null ? null : weather.weather;
        renderFeedNotice(c, weather, w != null);
        if (w == null) {
            return;
        }
        content.addView(Ui.kpiGrid(c, Arrays.asList(
                new String[] {"Temperature", w.temperatureC == null ? "n/a" : Fmt.number(w.temperatureC, 1) + " °C", w.description},
                new String[] {"Wind", w.windKmh == null ? "n/a" : Fmt.number(w.windKmh, 0) + " km/h", null},
                new String[] {"Humidity", w.humidityPct == null ? "n/a" : Fmt.number(w.humidityPct, 0) + "%", null},
                new String[] {"Rain, last hour", w.rainMm == null ? "n/a" : Fmt.number(w.rainMm, 1) + " mm", null})));
    }
}
