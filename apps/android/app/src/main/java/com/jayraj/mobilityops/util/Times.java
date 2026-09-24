package com.jayraj.mobilityops.util;

import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/** ISO timestamp parsing and calendar arithmetic without java.time (the app supports Android 7). */
public final class Times {
    private Times() {}

    /**
     * Epoch milliseconds of an ISO-8601 timestamp such as {@code 2026-09-24T13:09:54+00:00}
     * (fractional seconds allowed), or -1 when it cannot be read.
     */
    public static long parseIso(String iso) {
        if (iso == null) {
            return -1;
        }
        String s = iso.trim().replaceFirst("\\.\\d+", "").replaceFirst("Z$", "+00:00");
        try {
            SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US);
            f.setLenient(false);
            Date d = f.parse(s);
            return d == null ? -1 : d.getTime();
        } catch (ParseException e) {
            return -1;
        }
    }

    /** "2024-12-31" plus {@code days} (negative allowed), by plain calendar arithmetic. */
    public static String addDays(String yyyyMmDd, int days) {
        Calendar c = Calendar.getInstance(TimeZone.getTimeZone("UTC"), Locale.US);
        String[] p = yyyyMmDd.substring(0, 10).split("-");
        c.clear();
        c.set(Integer.parseInt(p[0]), Integer.parseInt(p[1]) - 1, Integer.parseInt(p[2]));
        c.add(Calendar.DAY_OF_MONTH, days);
        return String.format(Locale.US, "%04d-%02d-%02d", c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1,
                c.get(Calendar.DAY_OF_MONTH));
    }

    /**
     * The two 7-day windows for a week-over-week comparison, as {aStart, aEnd, bStart, bEnd} with
     * half-open [start, end) dates. A is the EARLIER week and B the latest one: the API measures the
     * change from A to B, so a positive change means demand rose into the latest week. The earlier
     * week is clamped to the start of the data.
     */
    public static String[] weekOverWeek(String dataEndExclusive, String dataStart) {
        String bEnd = dataEndExclusive.substring(0, 10);
        String bStart = addDays(bEnd, -7);
        String aEnd = bStart;
        String aStart = addDays(bEnd, -14);
        String first = dataStart.substring(0, 10);
        if (aStart.compareTo(first) < 0) {
            aStart = first;
        }
        return new String[] {aStart, aEnd, bStart, bEnd};
    }

    /** Seconds between an ISO timestamp and now; -1 when the timestamp cannot be read. */
    public static long ageSeconds(String iso, long nowMs) {
        long t = parseIso(iso);
        return t < 0 ? -1 : Math.max(0, (nowMs - t) / 1000);
    }
}
