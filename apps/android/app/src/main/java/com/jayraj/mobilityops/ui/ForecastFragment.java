package com.jayraj.mobilityops.ui;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.core.content.ContextCompat;

import com.jayraj.mobilityops.R;
import com.jayraj.mobilityops.net.ApiClient;
import com.jayraj.mobilityops.net.ApiException;
import com.jayraj.mobilityops.util.Fmt;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.json.JSONArray;
import org.json.JSONObject;

/** How good the forecasts are (measured on held-out days) and the forecast for the next day. */
public final class ForecastFragment extends ScreenFragment {

    private static final String[][] MODELS = {
            {"lightgbm", "LightGBM (Poisson)"},
            {"seasonal_mean_4w", "Seasonal mean (last 4 weeks)"},
            {"seasonal_naive", "Seasonal naive (last week)"},
            {"naive", "Naive (yesterday)"},
    };

    private static final class Data {
        JSONObject perf;
        JSONObject nextDay; // null when no model has been trained yet
        String nextDayProblem;
    }

    @Override
    protected void build(@NonNull Context c) {
        content.addView(Ui.muted(c, "Loading forecast results…"));
        load(() -> fetch(api()), d -> show(c, d), e -> {
            content.removeAllViews();
            content.addView(errorView(c, e, () -> {
                content.removeAllViews();
                build(c);
            }));
        });
    }

    private static Data fetch(ApiClient api) throws IOException {
        Data d = new Data();
        d.perf = api.getObject("/api/v1/forecast/performance", null);
        try {
            d.nextDay = api.getObject("/api/v1/forecast/next-day", null);
        } catch (ApiException e) {
            d.nextDayProblem = e.getMessage(); // the accuracy part is still worth showing
        }
        return d;
    }

    private void show(Context c, Data d) {
        content.removeAllViews();
        JSONObject overall = d.perf.optJSONObject("overall");
        JSONObject interval = d.perf.optJSONObject("interval");
        JSONObject cov = interval == null ? null : interval.optJSONObject("overall");
        JSONObject lgbm = overall == null ? null : overall.optJSONObject("lightgbm");
        String best = d.perf.optString("best_baseline", "");
        JSONObject bestM = overall == null ? null : overall.optJSONObject(best);

        content.addView(Ui.banner(c, d.perf.optString("data_label", "").toUpperCase(java.util.Locale.ROOT),
                "Accuracy below was measured on " + d.perf.optInt("test_days") + " held-out days (walk-forward: the model "
                        + "never saw them when it forecast them).", R.color.live_bg, R.color.live_border));
        content.addView(Ui.heading(c, "Accuracy on held-out days"));
        content.addView(Ui.kpiGrid(c, Arrays.asList(
                new String[] {"Model error (WAPE)", lgbm == null ? "n/a" : Fmt.percent(dbl(lgbm, "wape"), 1), "per zone and hour; lower is better"},
                new String[] {"Best simple baseline", bestM == null ? "n/a" : Fmt.percent(dbl(bestM, "wape"), 1), label(best)},
                new String[] {"80% interval coverage", cov == null ? "n/a" : Fmt.percent(dbl(cov, "coverage"), 1), "target 80%"},
                new String[] {"Test zone-hours", Fmt.integer((long) d.perf.optLong("test_rows")), null})));

        List<String[]> rows = new ArrayList<>();
        for (String[] m : MODELS) {
            JSONObject o = overall == null ? null : overall.optJSONObject(m[0]);
            if (o != null) {
                rows.add(new String[] {m[1], Fmt.percent(dbl(o, "wape"), 1), Fmt.number(dbl(o, "mae"), 2)});
            }
        }
        content.addView(Ui.table(c, new String[] {"Model", "WAPE", "MAE"}, rows, new boolean[] {false, true, true}));
        content.addView(Ui.muted(c, "WAPE is total absolute error divided by total pickups. Forecasts are estimates, "
                + "not guarantees."));

        content.addView(Ui.heading(c, "Forecast for the next day"));
        if (d.nextDay == null) {
            content.addView(Ui.body(c, "Not available: " + d.nextDayProblem));
            return;
        }
        JSONArray pts = d.nextDay.optJSONArray("points");
        int n = pts == null ? 0 : pts.length();
        double[] f = new double[n];
        String[] labels = new String[n];
        for (int i = 0; i < n; i++) {
            JSONObject p = pts.optJSONObject(i);
            f[i] = p == null ? Double.NaN : p.optDouble("forecast");
            String ts = p == null ? "" : p.optString("hour_ts", "");
            labels[i] = ts.length() >= 13 ? ts.substring(11, 13) + ":00" : "";
        }
        content.addView(Ui.muted(c, "City total for " + d.nextDay.optString("target_date") + ", model "
                + d.nextDay.optString("model_id") + "."));
        LineChartView chart = Ui.chart(c);
        chart.setData(labels, Arrays.asList(new LineChartView.Series("Forecast pickups per hour",
                ContextCompat.getColor(c, R.color.series1), f, false)),
                "Forecast city pickups for each hour of " + d.nextDay.optString("target_date") + ".");
        content.addView(chart);
        content.addView(Ui.muted(c, d.nextDay.optString("note", "")));
    }

    private static Double dbl(JSONObject o, String key) {
        return o.isNull(key) || !o.has(key) ? null : o.optDouble(key);
    }

    private static String label(String key) {
        for (String[] m : MODELS) {
            if (m[0].equals(key)) {
                return m[1];
            }
        }
        return key;
    }
}
