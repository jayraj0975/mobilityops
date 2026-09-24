package com.jayraj.mobilityops.pune

import androidx.fragment.app.Fragment
import com.jayraj.mobilityops.R

/** Screens reached from other screens (not from the tab bar). */
object PuneNav {
    fun zone(from: Fragment, id: Int) {
        from.parentFragmentManager.beginTransaction()
            .replace(R.id.container, PuneZoneFragment.of(id))
            .addToBackStack("zone")
            .commit()
    }

    fun settings(from: Fragment) {
        from.parentFragmentManager.beginTransaction()
            .replace(R.id.container, com.jayraj.mobilityops.ui.SettingsFragment())
            .addToBackStack("settings")
            .commit()
    }
}
