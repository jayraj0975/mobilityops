package com.jayraj.mobilityops.util;

import java.util.Locale;

/** Number and time formatting shared by every screen. Missing values read "n/a", never 0. */
public final class Fmt {
    private Fmt() {}

    public static String integer(Double x) {
        if (x == null || x.isNaN() || x.isInfinite()) {
            return "n/a";
        }
        return String.format(Locale.US, "%,d", Math.round(x));
    }

    public static String integer(long x) {
        return String.format(Locale.US, "%,d", x);
    }

    public static String number(Double x, int digits) {
        if (x == null || x.isNaN() || x.isInfinite()) {
            return "n/a";
        }
        return String.format(Locale.US, "%,." + digits + "f", x);
    }

    /** A share (0.187) as a percentage ("18.7%"). */
    public static String percent(Double x, int digits) {
        if (x == null || x.isNaN() || x.isInfinite()) {
            return "n/a";
        }
        return String.format(Locale.US, "%." + digits + "f%%", 100 * x);
    }

    /** A signed change ("+12.3%" or "-4.0%"). */
    public static String signedPercent(Double x, int digits) {
        if (x == null || x.isNaN() || x.isInfinite()) {
            return "n/a";
        }
        return String.format(Locale.US, "%+." + digits + "f%%", 100 * x);
    }

    /** "12 s ago", "5 min ago", "3 h ago" from an age in seconds. */
    public static String age(long seconds) {
        long s = Math.max(0, seconds);
        if (s < 90) {
            return s + " s ago";
        }
        long m = Math.round(s / 60.0);
        return m < 90 ? m + " min ago" : Math.round(m / 60.0) + " h ago";
    }

    /** "2024-11-06T13:00:00" to "2024-11-06 13:00". */
    public static String hour(String iso) {
        if (iso == null || iso.length() < 16) {
            return iso == null ? "n/a" : iso;
        }
        return iso.substring(0, 16).replace('T', ' ');
    }
}
