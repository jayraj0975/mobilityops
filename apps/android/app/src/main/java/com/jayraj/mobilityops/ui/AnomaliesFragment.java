package com.jayraj.mobilityops.ui;

import android.content.Context;
import android.widget.LinearLayout;

import androidx.annotation.NonNull;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.button.MaterialButtonToggleGroup;
import com.jayraj.mobilityops.R;
import com.jayraj.mobilityops.util.Fmt;

import java.util.LinkedHashMap;
import java.util.Map;

import org.json.JSONArray;
import org.json.JSONObject;

/** Detected anomaly events, largest first, filterable by severity. Explanations never assert a cause. */
public final class AnomaliesFragment extends ScreenFragment {
    private static final String[][] FILTERS = {{"All", ""}, {"High", "high"}, {"Medium", "medium"}, {"Low", "low"}};
    private String severity = "";
    private LinearLayout results;

    @Override
    protected void build(@NonNull Context c) {
        content.addView(Ui.heading(c, "Anomaly events"));
        MaterialButtonToggleGroup group = new MaterialButtonToggleGroup(c);
        group.setSingleSelection(true);
        group.setSelectionRequired(true);
        for (int i = 0; i < FILTERS.length; i++) {
            MaterialButton b = new MaterialButton(c, null, com.google.android.material.R.attr.materialButtonOutlinedStyle);
            b.setText(FILTERS[i][0]);
            b.setId(1000 + i);
            b.setContentDescription("Show " + FILTERS[i][0] + " severity events");
            group.addView(b);
        }
        group.check(1000 + indexOf(severity));
        group.addOnButtonCheckedListener((g, id, checked) -> {
            if (checked) {
                severity = FILTERS[id - 1000][1];
                refresh(c);
            }
        });
        content.addView(group);
        results = new LinearLayout(c);
        results.setOrientation(LinearLayout.VERTICAL);
        content.addView(results);
        refresh(c);
    }

    private static int indexOf(String value) {
        for (int i = 0; i < FILTERS.length; i++) {
            if (FILTERS[i][1].equals(value)) {
                return i;
            }
        }
        return 0;
    }

    private void refresh(Context c) {
        results.removeAllViews();
        results.addView(Ui.muted(c, "Loading events…"));
        Map<String, String> q = new LinkedHashMap<>();
        q.put("limit", "40");
        if (!severity.isEmpty()) {
            q.put("severity", severity);
        }
        load(() -> api().getObject("/api/v1/anomalies", q), page -> {
            if (results == null) {
                return;
            }
            results.removeAllViews();
            results.addView(Ui.muted(c, page.optInt("total") + " events, largest first. "
                    + page.optString("accuracy_status", "")));
            JSONArray items = page.optJSONArray("items");
            if (items == null || items.length() == 0) {
                results.addView(Ui.body(c, "No events for this filter."));
                return;
            }
            for (int i = 0; i < items.length(); i++) {
                JSONObject e = items.optJSONObject(i);
                if (e != null) {
                    results.addView(eventCard(c, e));
                }
            }
        }, e -> {
            if (results == null) {
                return;
            }
            results.removeAllViews();
            results.addView(errorView(c, e, () -> refresh(c)));
        });
    }

    private android.view.View eventCard(Context c, JSONObject e) {
        LinearLayout box = new LinearLayout(c);
        box.setOrientation(LinearLayout.VERTICAL);
        int p = Ui.dp(c, 12);
        box.setPadding(p, p, p, p);
        String head = e.optString("zone") + " (" + e.optString("borough") + ")";
        box.addView(Ui.text(c, head, 16, R.color.text, true));
        int sevColor = "high".equals(e.optString("severity")) ? R.color.fail
                : "medium".equals(e.optString("severity")) ? R.color.warn : R.color.muted;
        box.addView(Ui.text(c, e.optString("direction") + " · " + e.optString("severity") + " severity · "
                + e.optInt("hours_span") + " h · " + Fmt.hour(e.optString("start")), 13, sevColor, true));
        box.addView(Ui.body(c, "Actual " + Fmt.integer(e.optDouble("actual")) + " against a forecast of "
                + Fmt.integer(e.optDouble("forecast")) + " (" + Fmt.number(e.optDouble("excess"), 0) + " difference)."));
        box.addView(Ui.muted(c, e.optString("explanation", "")));
        com.google.android.material.card.MaterialCardView card = new com.google.android.material.card.MaterialCardView(c);
        card.setCardBackgroundColor(androidx.core.content.ContextCompat.getColor(c, R.color.surface));
        card.setStrokeColor(androidx.core.content.ContextCompat.getColor(c, R.color.border));
        card.setStrokeWidth(Ui.dp(c, 1));
        card.setRadius(Ui.dp(c, 8));
        card.setCardElevation(0);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                android.view.ViewGroup.LayoutParams.MATCH_PARENT, android.view.ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, Ui.dp(c, 4), 0, Ui.dp(c, 4));
        card.setLayoutParams(lp);
        card.addView(box);
        return card;
    }

    @Override
    public void onDestroyView() {
        results = null;
        super.onDestroyView();
    }
}
