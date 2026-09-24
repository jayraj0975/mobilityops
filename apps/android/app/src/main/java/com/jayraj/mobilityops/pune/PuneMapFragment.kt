package com.jayraj.mobilityops.pune

import android.content.Context
import android.view.View
import android.widget.ArrayAdapter
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.Spinner
import android.widget.AdapterView
import com.google.android.material.button.MaterialButton
import com.jayraj.mobilityops.ui.Ui

/** Live map: zones coloured by demand against the forecast, with a time control and layers. */
class PuneMapFragment : PuneScreen() {
    private var geometry: Geometry? = null
    private var geometryError: String? = null
    private var selector = "now"
    private var other: Snapshot? = null
    private var layer = MapLayer.RATIO
    private var selected: Int? = null

    override fun onNewData() {
        if (geometry == null) {
            load({ PuneClient(api()).geometry() }, { geometry = it; geometryError = null; redraw() }, { geometryError = it.message; redraw() })
        }
        loadOther()
    }

    private fun loadOther() {
        if (selector == "now") {
            other = null
            return
        }
        val at = selector
        load({ PuneClient(api()).snapshot(at) }, { if (selector == at) { other = it; redraw() } }, { redraw() })
    }

    private fun current(): Snapshot? = if (selector == "now") st.snapshot else other

    override fun render(c: Context) {
        header(c, "Live map")
        val g = geometry
        if (g == null) {
            content.addView(Ui.muted(c, geometryError ?: "Loading the map…"))
            return
        }
        val s = current()
        content.addView(timeRow(c))
        if (s == null) {
            content.addView(Ui.muted(c, "Loading…"))
            return
        }
        content.addView(Ui.muted(c, s.windowNote))
        val layerRow = Spinner(c).apply {
            adapter = ArrayAdapter(c, android.R.layout.simple_spinner_dropdown_item, MapLayer.entries.map { it.label })
            setSelection(layer.ordinal, false)
            contentDescription = "Map layer"
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                    if (MapLayer.entries[pos] != layer) {
                        layer = MapLayer.entries[pos]
                        redraw()
                    }
                }
                override fun onNothingSelected(p: AdapterView<*>?) {}
            }
        }
        content.addView(layerRow)
        val map = ZoneMapView(c).apply {
            setGeometry(g)
            setData(s.zones, layer)
            selectedId = selected
            contentDescription = "Map of ${g.zones.size} Pune zones coloured by ${layer.label.lowercase()}. Use the zone list below for a screen-reader route."
            onZoneTap = { id -> selected = id; redraw() }
        }
        content.addView(map, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        content.addView(Ui.muted(c, legend()))
        val z = g.zones.firstOrNull { it.id == selected }
        val v = s.zones.firstOrNull { it.id == selected }
        if (z != null && v != null) {
            content.addView(Ui.subheading(c, "${z.name} (${z.sector})"))
            content.addView(
                Ui.body(
                    c,
                    "Pickups ${fmtInt(v.actual)} · forecast ${fmtInt(v.forecast)} (${fmtInt(v.lo)} to ${fmtInt(v.hi)})" +
                        (v.ratio?.let { " · ${Math.round(it * 100)}% of forecast" } ?: "") +
                        (if (v.status != "normal") " · ${v.status.uppercase()}" else ""),
                ),
            )
            content.addView(MaterialButton(c).apply { text = "Zone details"; setOnClickListener { PuneNav.zone(this@PuneMapFragment, z.id) } })
        } else {
            content.addView(Ui.muted(c, "Tap a zone to read its numbers."))
        }
        content.addView(Ui.subheading(c, "Zones that stand out"))
        s.zones.sortedByDescending { Math.abs(it.z ?: 0.0) }.take(8).forEach { zv ->
            val name = g.zones.firstOrNull { it.id == zv.id }?.name ?: "zone ${zv.id}"
            content.addView(
                MaterialButton(c, null, com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
                    text = "$name · ${zv.ratio?.let { "${Math.round(it * 100)}% of forecast" } ?: "n/a"}"
                    isAllCaps = false
                    setOnClickListener { selected = zv.id; redraw() }
                },
            )
        }
        content.addView(Ui.muted(c, "${g.attribution}. Zones are the service areas of OpenStreetMap suburbs, not administrative wards."))
    }

    private fun legend(): String = when (layer) {
        MapLayer.RATIO -> "Blue: below forecast (down to 0.5×). Grey: as forecast. Orange: above (up to 1.5×)."
        MapLayer.EVENTS -> "Orange: a detected surge. Blue: a detected drop. Grey: none."
        MapLayer.DEMAND -> "Light to dark: fewer to more simulated pickups in the window."
        MapLayer.FORECAST -> "Light to dark: lower to higher forecast in the window."
    }

    private fun timeRow(c: Context): View {
        val row = LinearLayout(c).apply { orientation = LinearLayout.HORIZONTAL }
        for ((id, label) in TIMES) {
            row.addView(
                MaterialButton(c, null, com.google.android.material.R.attr.materialButtonOutlinedStyle).apply {
                    text = label
                    isAllCaps = false
                    isChecked = false
                    alpha = if (selector == id) 1f else 0.6f
                    contentDescription = if (selector == id) "$label, selected" else label
                    setOnClickListener {
                        selector = id
                        other = null
                        loadOther()
                        redraw()
                    }
                },
            )
        }
        return HorizontalScrollView(c).apply { addView(row) }
    }

    companion object {
        val TIMES = listOf("now" to "NOW", "-15m" to "−15 min", "-1h" to "−1 h", "-6h" to "−6 h", "today" to "TODAY", "forecast" to "FORECAST")
    }
}
