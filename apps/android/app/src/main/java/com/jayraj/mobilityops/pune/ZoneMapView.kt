package com.jayraj.mobilityops.pune

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Region
import android.graphics.RectF
import android.view.MotionEvent
import android.view.View

/** Pune's zones drawn as polygons, coloured by the chosen layer. Tap a zone to select it. */
class ZoneMapView(context: Context) : View(context) {
    private var geometry: Geometry? = null
    private var proj: Projection? = null
    private var paths: List<Path> = emptyList()
    private var values: Map<Int, ZoneValue> = emptyMap()
    private var layer = MapLayer.RATIO
    private var max = 0.0
    var selectedId: Int? = null
        set(v) {
            field = v
            invalidate()
        }
    var onZoneTap: ((Int?) -> Unit)? = null
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 1.2f * resources.displayMetrics.density
        color = 0xFF0F172A.toInt()
    }
    private val selStroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 3.5f * resources.displayMetrics.density
        color = 0xFFFBBF24.toInt()
    }

    fun setGeometry(g: Geometry) {
        geometry = g
        proj = Projection(g.bbox)
        rebuild()
    }

    fun setData(values: List<ZoneValue>, layer: MapLayer) {
        this.values = values.associateBy { it.id }
        this.layer = layer
        max = values.maxOfOrNull { if (layer == MapLayer.DEMAND) it.actual ?: 0.0 else it.forecast } ?: 0.0
        invalidate()
    }

    override fun onMeasure(widthSpec: Int, heightSpec: Int) {
        val w = MeasureSpec.getSize(widthSpec)
        val p = proj
        val h = if (p == null) w else (w * p.height / p.width).toInt()
        setMeasuredDimension(w, h)
    }

    override fun onSizeChanged(w: Int, h: Int, ow: Int, oh: Int) {
        super.onSizeChanged(w, h, ow, oh)
        rebuild()
    }

    private fun rebuild() {
        val g = geometry ?: return
        val p = proj ?: return
        if (width == 0) return
        val s = width / p.width
        paths = g.zones.map { z ->
            Path().apply {
                z.ring.forEachIndexed { i, pt ->
                    val x = (p.x(pt[0]) * s).toFloat()
                    val y = (p.y(pt[1]) * s).toFloat()
                    if (i == 0) moveTo(x, y) else lineTo(x, y)
                }
                close()
            }
        }
        requestLayout()
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        val g = geometry ?: return
        g.zones.forEachIndexed { i, z ->
            val path = paths.getOrNull(i) ?: return@forEachIndexed
            fill.color = MapColors.forLayer(layer, values[z.id], max)
            canvas.drawPath(path, fill)
            canvas.drawPath(path, stroke)
        }
        val sel = g.zones.indexOfFirst { it.id == selectedId }
        if (sel >= 0) paths.getOrNull(sel)?.let { canvas.drawPath(it, selStroke) }
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        if (e.action == MotionEvent.ACTION_UP) {
            val g = geometry ?: return true
            val region = Region()
            val bounds = Region(0, 0, width, height)
            val hit = paths.indexOfFirst { path ->
                val rf = RectF()
                path.computeBounds(rf, true)
                region.setPath(path, bounds)
                region.contains(e.x.toInt(), e.y.toInt())
            }
            val id = if (hit >= 0) g.zones[hit].id else null
            selectedId = if (id == selectedId) null else id
            onZoneTap?.invoke(selectedId)
            performClick()
        }
        return true
    }

    override fun performClick(): Boolean = super.performClick()
}
