package com.jayraj.mobilityops.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.util.AttributeSet;
import android.view.View;

import androidx.annotation.ColorInt;
import androidx.annotation.Nullable;

import com.jayraj.mobilityops.util.Fmt;

import java.util.ArrayList;
import java.util.List;

/**
 * A small multi-line chart drawn with the Canvas: gridlines, min/max labels, first and last x
 * labels and a legend. It keeps a plain-language description for screen readers.
 */
public final class LineChartView extends View {

    public static final class Series {
        final String label;
        final @ColorInt int color;
        final double[] values;
        final boolean dashed;

        public Series(String label, @ColorInt int color, double[] values, boolean dashed) {
            this.label = label;
            this.color = color;
            this.values = values;
            this.dashed = dashed;
        }
    }

    private final Paint linePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint gridPaint = new Paint();
    private final Paint textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();
    private final android.graphics.DashPathEffect dash = new android.graphics.DashPathEffect(new float[] {12f, 8f}, 0);
    private final List<Series> series = new ArrayList<>();
    private String[] xLabels = new String[0];
    private @ColorInt int gridColor = 0x33888888;
    private @ColorInt int textColor = 0xFF888888;
    private final float dp;

    public LineChartView(Context context) {
        this(context, null);
    }

    public LineChartView(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        dp = context.getResources().getDisplayMetrics().density;
        linePaint.setStyle(Paint.Style.STROKE);
        linePaint.setStrokeWidth(2f * dp);
        linePaint.setStrokeJoin(Paint.Join.ROUND);
        gridPaint.setStrokeWidth(1f);
        textPaint.setTextSize(11f * dp);
        setMinimumHeight((int) (220 * dp));
    }

    public void setColors(@ColorInt int grid, @ColorInt int text) {
        gridColor = grid;
        textColor = text;
        invalidate();
    }

    /** Replace the data. All series share the x labels; a series may be shorter (drawn from the left). */
    public void setData(String[] labels, List<Series> newSeries, String description) {
        xLabels = labels == null ? new String[0] : labels;
        series.clear();
        series.addAll(newSeries);
        setContentDescription(description);
        invalidate();
    }

    @Override
    protected void onMeasure(int widthSpec, int heightSpec) {
        int w = MeasureSpec.getSize(widthSpec);
        setMeasuredDimension(w, (int) (240 * dp));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        int n = 0;
        double lo = Double.POSITIVE_INFINITY;
        double hi = Double.NEGATIVE_INFINITY;
        for (Series s : series) {
            n = Math.max(n, s.values.length);
            for (double v : s.values) {
                if (!Double.isNaN(v)) {
                    lo = Math.min(lo, v);
                    hi = Math.max(hi, v);
                }
            }
        }
        float w = getWidth();
        float h = getHeight();
        float legendH = 22 * dp;
        float left = 52 * dp;
        float right = 8 * dp;
        float top = legendH + 6 * dp;
        float bottom = h - 20 * dp;
        textPaint.setColor(textColor);

        if (n < 2 || Double.isInfinite(lo)) {
            textPaint.setTextAlign(Paint.Align.CENTER);
            canvas.drawText("Waiting for data…", w / 2, h / 2, textPaint);
            return;
        }
        if (hi - lo < 1e-9) {
            hi = lo + 1;
        }
        boolean nonNegative = lo >= 0;
        double pad = (hi - lo) * 0.08;
        lo -= pad;
        hi += pad;
        if (nonNegative && lo < 0) {
            lo = 0; // counts never go below zero; do not draw an axis that says they can
        }

        gridPaint.setColor(gridColor);
        textPaint.setTextAlign(Paint.Align.RIGHT);
        for (int i = 0; i <= 3; i++) {
            float y = top + (bottom - top) * i / 3f;
            canvas.drawLine(left, y, w - right, y, gridPaint);
            double value = hi - (hi - lo) * i / 3.0;
            canvas.drawText(Fmt.integer(value), left - 4 * dp, y + 4 * dp, textPaint);
        }
        textPaint.setTextAlign(Paint.Align.LEFT);
        if (xLabels.length > 0) {
            canvas.drawText(xLabels[0], left, h - 4 * dp, textPaint);
            textPaint.setTextAlign(Paint.Align.RIGHT);
            canvas.drawText(xLabels[Math.min(n, xLabels.length) - 1], w - right, h - 4 * dp, textPaint);
        }

        for (Series s : series) {
            linePaint.setColor(s.color);
            linePaint.setPathEffect(s.dashed ? dash : null);
            path.reset();
            boolean started = false;
            for (int i = 0; i < s.values.length; i++) {
                if (Double.isNaN(s.values[i])) {
                    started = false;
                    continue;
                }
                float x = left + (w - left - right) * i / (float) (n - 1);
                float y = (float) (bottom - (bottom - top) * (s.values[i] - lo) / (hi - lo));
                if (!started) {
                    path.moveTo(x, y);
                    started = true;
                } else {
                    path.lineTo(x, y);
                }
            }
            canvas.drawPath(path, linePaint);
        }
        linePaint.setPathEffect(null);

        float x = left;
        textPaint.setTextAlign(Paint.Align.LEFT);
        for (Series s : series) {
            linePaint.setColor(s.color);
            canvas.drawLine(x, legendH / 2, x + 16 * dp, legendH / 2, linePaint);
            canvas.drawText(s.label, x + 20 * dp, legendH / 2 + 4 * dp, textPaint);
            x += 28 * dp + textPaint.measureText(s.label);
        }
    }
}
