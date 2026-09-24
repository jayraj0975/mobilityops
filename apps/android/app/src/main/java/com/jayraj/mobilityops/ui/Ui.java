package com.jayraj.mobilityops.ui;

import android.content.Context;
import android.graphics.Typeface;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.GridLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.ColorRes;
import androidx.core.content.ContextCompat;
import androidx.core.view.ViewCompat;

import com.google.android.material.card.MaterialCardView;
import com.jayraj.mobilityops.R;

import java.util.List;

/** Small view builders so each screen reads as a list of sections rather than layout plumbing. */
public final class Ui {
    private Ui() {}

    public static int dp(Context c, int v) {
        return Math.round(v * c.getResources().getDisplayMetrics().density);
    }

    public static TextView text(Context c, String s, float sp, @ColorRes int color, boolean bold) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(ContextCompat.getColor(c, color));
        if (bold) {
            t.setTypeface(t.getTypeface(), Typeface.BOLD);
        }
        return t;
    }

    public static TextView heading(Context c, String s) {
        TextView t = text(c, s, 20, R.color.text, true);
        t.setPadding(0, dp(c, 20), 0, dp(c, 6));
        ViewCompat.setAccessibilityHeading(t, true);
        return t;
    }

    public static TextView subheading(Context c, String s) {
        TextView t = text(c, s, 16, R.color.text, true);
        t.setPadding(0, dp(c, 12), 0, dp(c, 4));
        ViewCompat.setAccessibilityHeading(t, true);
        return t;
    }

    public static TextView body(Context c, String s) {
        TextView t = text(c, s, 15, R.color.text, false);
        t.setPadding(0, dp(c, 2), 0, dp(c, 2));
        return t;
    }

    public static TextView muted(Context c, String s) {
        TextView t = text(c, s, 13, R.color.muted, false);
        t.setPadding(0, dp(c, 2), 0, dp(c, 2));
        return t;
    }

    /** A bordered, tinted note used to say what kind of data a section shows (REPLAY / LIVE). */
    public static View banner(Context c, String strong, String rest, @ColorRes int bg, @ColorRes int border) {
        MaterialCardView card = new MaterialCardView(c);
        card.setCardBackgroundColor(ContextCompat.getColor(c, bg));
        card.setStrokeColor(ContextCompat.getColor(c, border));
        card.setStrokeWidth(dp(c, 2));
        card.setRadius(dp(c, 8));
        card.setCardElevation(0);
        LinearLayout box = new LinearLayout(c);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(c, 12), dp(c, 10), dp(c, 12), dp(c, 10));
        box.addView(text(c, strong, 14, R.color.text, true));
        box.addView(text(c, rest, 14, R.color.text, false));
        card.addView(box);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(c, 6), 0, dp(c, 6));
        card.setLayoutParams(lp);
        return card;
    }

    /** One number with a label and an optional note. */
    public static View kpi(Context c, String label, String value, String note) {
        MaterialCardView card = new MaterialCardView(c);
        card.setCardBackgroundColor(ContextCompat.getColor(c, R.color.surface));
        card.setStrokeColor(ContextCompat.getColor(c, R.color.border));
        card.setStrokeWidth(dp(c, 1));
        card.setRadius(dp(c, 8));
        card.setCardElevation(0);
        LinearLayout box = new LinearLayout(c);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(c, 12), dp(c, 10), dp(c, 12), dp(c, 10));
        box.addView(text(c, label, 12, R.color.muted, false));
        box.addView(text(c, value, 22, R.color.text, true));
        if (note != null && !note.isEmpty()) {
            box.addView(text(c, note, 12, R.color.muted, false));
        }
        card.addView(box);
        card.setContentDescription(label + ": " + value + (note == null ? "" : ". " + note));
        return card;
    }

    /** Tiles laid out two per row. Each entry is {label, value, note}. */
    public static View kpiGrid(Context c, List<String[]> items) {
        GridLayout grid = new GridLayout(c);
        grid.setColumnCount(2);
        grid.setUseDefaultMargins(false);
        for (String[] k : items) {
            View tile = kpi(c, k[0], k[1], k.length > 2 ? k[2] : null);
            GridLayout.LayoutParams lp = new GridLayout.LayoutParams(
                    GridLayout.spec(GridLayout.UNDEFINED, 1f), GridLayout.spec(GridLayout.UNDEFINED, 1f));
            lp.width = 0;
            lp.height = ViewGroup.LayoutParams.WRAP_CONTENT;
            lp.setMargins(dp(c, 3), dp(c, 3), dp(c, 3), dp(c, 3));
            grid.addView(tile, lp);
        }
        return grid;
    }

    /** A simple table: header row plus rows. Numeric columns are right-aligned. */
    public static View table(Context c, String[] headers, List<String[]> rows, boolean[] numeric) {
        LinearLayout t = new LinearLayout(c);
        t.setOrientation(LinearLayout.VERTICAL);
        t.addView(tableRow(c, headers, numeric, true));
        for (String[] r : rows) {
            t.addView(tableRow(c, r, numeric, false));
        }
        return t;
    }

    private static View tableRow(Context c, String[] cells, boolean[] numeric, boolean header) {
        LinearLayout row = new LinearLayout(c);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, dp(c, 5), 0, dp(c, 5));
        StringBuilder spoken = new StringBuilder();
        for (int i = 0; i < cells.length; i++) {
            TextView cell = text(c, cells[i], header ? 12 : 14, header ? R.color.muted : R.color.text, header);
            boolean num = numeric != null && i < numeric.length && numeric[i];
            cell.setGravity(num ? Gravity.END : Gravity.START);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, i == 0 ? 2f : 1f);
            row.addView(cell, lp);
            spoken.append(cells[i]).append(i < cells.length - 1 ? ", " : "");
        }
        row.setContentDescription(spoken.toString());
        return row;
    }

    public static LineChartView chart(Context c) {
        LineChartView v = new LineChartView(c);
        v.setColors(ContextCompat.getColor(c, R.color.grid), ContextCompat.getColor(c, R.color.muted));
        return v;
    }
}
