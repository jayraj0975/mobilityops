package com.jayraj.mobilityops.ui;

import android.content.Context;

import androidx.annotation.NonNull;

import com.jayraj.mobilityops.R;
import com.jayraj.mobilityops.net.ApiClient;
import com.jayraj.mobilityops.net.ApiException;
import com.jayraj.mobilityops.util.Fmt;
import com.jayraj.mobilityops.util.Times;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.json.JSONArray;
import org.json.JSONObject;

/** What the data is, the last week against the week before, the busiest zones, and the service mix. */
public final class OverviewFragment extends ScreenFragment {

    private static final class Data {
        JSONObject meta;
        JSONObject compare;
        JSONArray top;
        JSONArray services; // null when the database holds yellow taxis only
        String from;
        String to;
    }

    @Override
    protected void build(@NonNull Context c) {
        content.addView(Ui.muted(c, "Loading overview…"));
        load(() -> fetch(api()), data -> show(c, data), e -> {
            content.removeAllViews();
            content.addView(errorView(c, e, () -> {
                content.removeAllViews();
                build(c);
            }));
        });
    }

    private static Data fetch(ApiClient api) throws IOException {
        Data d = new Data();
        d.meta = api.getObject("/api/v1/meta", null);
        String endExclusive = d.meta.optString("data_end", "").substring(0, 10);
        String start = d.meta.optString("data_start", "").substring(0, 10);
        String[] w = Times.weekOverWeek(endExclusive, start);
        String weekAgo = w[2];
        d.from = weekAgo;
        d.to = Times.addDays(endExclusive, -1);
        Map<String, String> cmp = new LinkedHashMap<>();
        cmp.put("a_start", w[0]); // the earlier week
        cmp.put("a_end", w[1]);
        cmp.put("b_start", w[2]); // the latest week: the change is measured from A to B
        cmp.put("b_end", w[3]);
        d.compare = api.getObject("/api/v1/demand/compare", cmp);
        Map<String, String> top = new LinkedHashMap<>();
        top.put("start", weekAgo);
        top.put("end", endExclusive);
        top.put("limit", "8");
        d.top = api.getArray("/api/v1/demand/top-zones", top);
        JSONArray svc = d.meta.optJSONArray("services");
        if (svc != null && svc.length() > 1) {
            Map<String, String> q = new LinkedHashMap<>();
            q.put("start", start);
            q.put("end", endExclusive);
            q.put("grain", "total");
            try {
                d.services = api.getArray("/api/v1/demand/services", q);
            } catch (ApiException e) {
                d.services = null; // optional: the rest of the screen still works
            }
        }
        return d;
    }

    private void show(Context c, Data d) {
        content.removeAllViews();
        boolean synthetic = d.meta.optBoolean("synthetic", false);
        String label = d.meta.optString("data_label", "").toUpperCase(java.util.Locale.ROOT);
        content.addView(Ui.banner(c, label,
                synthetic ? "generated for tests and demos; these are not real trips."
                        : "NYC TLC taxi trips, " + d.meta.optString("data_start", "").substring(0, 10) + " to "
                                + Times.addDays(d.meta.optString("data_end", "").substring(0, 10), -1) + ".",
                synthetic ? R.color.surface : R.color.live_bg, synthetic ? R.color.warn : R.color.live_border));

        content.addView(Ui.heading(c, "Last 7 days"));
        JSONObject earlier = d.compare.optJSONObject("period_a");
        JSONObject latest = d.compare.optJSONObject("period_b");
        Double change = d.compare.isNull("per_day_change_pct") ? null : d.compare.optDouble("per_day_change_pct");
        content.addView(Ui.kpiGrid(c, Arrays.asList(
                new String[] {"Pickups per day", latest == null ? "n/a" : Fmt.integer(latest.optDouble("per_day")), d.from + " to " + d.to},
                new String[] {"Change vs previous week", Fmt.signedPercent(change, 1),
                        earlier == null ? null : "was " + Fmt.integer(earlier.optDouble("per_day")) + " per day"},
                new String[] {"Zones in the data", Fmt.integer((long) d.meta.optInt("n_zones")), null},
                new String[] {"Trips analysed", Fmt.integer((long) d.meta.optLong("rows_valid")), "after cleaning"})));
        if (!d.compare.optBoolean("equal_length", true)) {
            content.addView(Ui.muted(c, "The earlier period is shorter because the data starts there."));
        }

        content.addView(Ui.subheading(c, "Busiest zones, last 7 days"));
        List<String[]> rows = new ArrayList<>();
        for (int i = 0; i < d.top.length(); i++) {
            JSONObject z = d.top.optJSONObject(i);
            if (z != null) {
                rows.add(new String[] {z.optString("zone") + " (" + z.optString("borough") + ")",
                        Fmt.integer(z.optDouble("value")), Fmt.percent(z.optDouble("share"), 1)});
            }
        }
        content.addView(Ui.table(c, new String[] {"Zone", "Pickups", "Share of city"}, rows, new boolean[] {false, true, true}));

        if (d.services != null) {
            content.addView(Ui.subheading(c, "Yellow taxis, green taxis and for-hire vehicles"));
            content.addView(Ui.muted(c, "Share of the pickups counted in the three TLC files, whole period. It is not the "
                    + "share of all mobility in the city: subways, buses and private cars are not here."));
            List<String[]> svc = new ArrayList<>();
            for (int i = 0; i < d.services.length(); i++) {
                JSONObject s = d.services.optJSONObject(i);
                if (s != null) {
                    svc.add(new String[] {s.optString("label"), Fmt.integer(s.optDouble("pickups")),
                            Fmt.percent(s.optDouble("share"), 1)});
                }
            }
            content.addView(Ui.table(c, new String[] {"Service", "Pickups", "Share"}, svc, new boolean[] {false, true, true}));
        }
    }
}
