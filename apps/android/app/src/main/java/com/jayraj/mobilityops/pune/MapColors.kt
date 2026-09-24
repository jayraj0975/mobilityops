package com.jayraj.mobilityops.pune

import kotlin.math.cos
import kotlin.math.sqrt

/** Colour scales for the zone map; the same choices as the web console. */
object MapColors {
    private val BELOW = intArrayOf(59, 130, 246)
    private val MID = intArrayOf(120, 134, 156)
    private val ABOVE = intArrayOf(249, 115, 22)
    private val LOW = intArrayOf(186, 230, 253)
    private val HIGH = intArrayOf(3, 105, 161)
    const val IDLE = 0xFF94A3B8.toInt()

    private fun mix(a: IntArray, b: IntArray, t: Double): Int =
        (0xFF shl 24) or
            (Math.round(a[0] + (b[0] - a[0]) * t).toInt() shl 16) or
            (Math.round(a[1] + (b[1] - a[1]) * t).toInt() shl 8) or
            Math.round(a[2] + (b[2] - a[2]) * t).toInt()

    /** Ratio (actual / forecast) to colour: blue below, grey at 1.0, orange above; clamped to 0.5..1.5. */
    fun ratio(r: Double): Int {
        val t = ((r - 1.0) / 0.5).coerceIn(-1.0, 1.0)
        return if (t < 0) mix(MID, BELOW, -t) else mix(MID, ABOVE, t)
    }

    /** Light-to-deep-blue ramp, square-root scaled so quiet zones stay visible. */
    fun ramp(value: Double, max: Double): Int =
        if (max <= 0) mix(LOW, HIGH, 0.0) else mix(LOW, HIGH, sqrt((value / max).coerceIn(0.0, 1.0)))

    fun forLayer(layer: MapLayer, z: ZoneValue?, max: Double): Int = when {
        z == null -> IDLE
        layer == MapLayer.RATIO -> if (z.ratio == null || z.forecast < 1) IDLE else ratio(z.ratio)
        layer == MapLayer.EVENTS -> when (z.status) {
            "surge" -> mix(ABOVE, ABOVE, 0.0)
            "drop" -> mix(BELOW, BELOW, 0.0)
            else -> IDLE
        }
        layer == MapLayer.DEMAND -> ramp(z.actual ?: 0.0, max)
        else -> ramp(z.forecast, max)
    }
}

enum class MapLayer(val label: String) {
    RATIO("Versus forecast"), DEMAND("Demand"), FORECAST("Forecast"), EVENTS("Events")
}

/** Equirectangular projection of the study box onto a plane; north is up. */
class Projection(bbox: DoubleArray) {
    private val latMin = bbox[0]
    private val lonMin = bbox[1]
    private val latMax = bbox[2]
    private val k = cos(Math.toRadians((bbox[0] + bbox[2]) / 2))
    val width = (bbox[3] - lonMin) * k
    val height = latMax - latMin
    fun x(lon: Double): Double = (lon - lonMin) * k
    fun y(lat: Double): Double = latMax - lat
}
