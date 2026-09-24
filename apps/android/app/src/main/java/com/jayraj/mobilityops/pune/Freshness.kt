package com.jayraj.mobilityops.pune

import androidx.annotation.ColorRes
import com.jayraj.mobilityops.R

/** How old a value is, computed by the server from the source's own timestamps. */
enum class Freshness(val label: String, val glyph: String, @param:ColorRes val color: Int, val help: String) {
    LIVE("LIVE", "●", R.color.ok, "Arriving on schedule."),
    DELAYED("DELAYED", "◐", R.color.warn, "Later than expected, but recent enough to trust."),
    STALE("STALE", "▲", R.color.fail, "Old. Shown for reference; not current."),
    OFFLINE("OFFLINE", "▲", R.color.fail, "Nothing recent has arrived."),
    DISABLED("NOT CONFIGURED", "○", R.color.muted, "Not configured. Nothing is being fetched."),
    NOT_PERIODIC("STATIC", "○", R.color.muted, "Static or historical: freshness does not apply.");

    companion object {
        fun parse(name: String?): Freshness = entries.firstOrNull { it.name == name } ?: OFFLINE
    }

    /** "● LIVE": the glyph repeats the colour so colour is never the only cue. */
    fun badge(): String = "$glyph $label"
}

/** "just now", "42 s ago", "5 min ago", "3 h ago", "over a day ago". */
fun ageText(seconds: Double?): String {
    if (seconds == null || seconds.isNaN() || seconds.isInfinite()) return "never"
    val s = Math.round(maxOf(0.0, seconds))
    return when {
        s < 5 -> "just now"
        s < 90 -> "$s s ago"
        s < 90 * 60 -> "${Math.round(s / 60.0)} min ago"
        s < 36 * 3600 -> "${Math.round(s / 3600.0)} h ago"
        else -> "over a day ago"
    }
}
