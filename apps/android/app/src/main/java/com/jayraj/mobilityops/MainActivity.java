package com.jayraj.mobilityops;

import android.os.Build;
import android.os.Bundle;

import androidx.activity.EdgeToEdge;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.fragment.app.Fragment;

import com.google.android.material.bottomnavigation.BottomNavigationView;
import com.jayraj.mobilityops.net.ApiClient;
import com.jayraj.mobilityops.pune.PuneAlertsFragment;
import com.jayraj.mobilityops.pune.PuneForecastFragment;
import com.jayraj.mobilityops.pune.PuneHomeFragment;
import com.jayraj.mobilityops.pune.PuneMapFragment;
import com.jayraj.mobilityops.pune.PuneStatusFragment;
import com.jayraj.mobilityops.ui.AnomaliesFragment;
import com.jayraj.mobilityops.ui.ForecastFragment;
import com.jayraj.mobilityops.ui.LiveFragment;
import com.jayraj.mobilityops.ui.OverviewFragment;
import com.jayraj.mobilityops.ui.SettingsFragment;
import com.jayraj.mobilityops.util.Async;
import com.jayraj.mobilityops.util.Settings;

/**
 * One activity. The tabs depend on what the server serves: New York analytics (Live, Overview,
 * Forecast, Anomalies, Settings) or the Pune real-time console (Home, Map, Forecast, Alerts, Status).
 * The mode is asked of the server and remembered, so a start is instant. A fresh install opens on
 * Settings so the server address is set first.
 */
public final class MainActivity extends AppCompatActivity {
    private static final String KEY_TAB = "tab";
    private BottomNavigationView nav;
    private boolean pune;
    private Async.Task detect;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        if (Build.VERSION.SDK_INT >= 35) {
            // From Android 15 an app that targets it is drawn edge to edge whatever it asks for, so the
            // content would sit under the status bar. Pad it by the bars. The bottom navigation pads
            // itself for the gesture bar, and the manifest's adjustResize still resizes the window for the
            // keyboard, so neither is added here. Older versions keep their original, tested layout.
            EdgeToEdge.enable(this);
            ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.root), (view, insets) -> {
                Insets bars = insets.getInsets(
                        WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout());
                view.setPadding(bars.left, bars.top, bars.right, 0);
                return insets;
            });
        }
        nav = findViewById(R.id.bottom_nav);
        Settings settings = new Settings(this);
        pune = "pune".equals(settings.mode());
        if (pune) {
            nav.getMenu().clear();
            nav.inflateMenu(R.menu.bottom_nav_pune);
        }
        nav.setOnItemSelectedListener(item -> {
            show(fragmentFor(item.getItemId()));
            return true;
        });
        if (savedInstanceState == null) {
            nav.setSelectedItemId(startTab(settings.isConfigured()));
        } else {
            nav.setSelectedItemId(savedInstanceState.getInt(KEY_TAB, startTab(true)));
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        Settings settings = new Settings(this);
        if (!settings.isConfigured()) {
            return;
        }
        // Ask the server which mode it is in; a change (or a new server in Settings) swaps the tabs.
        detect = Async.run(
                () -> new ApiClient(settings.serverUrl(), settings.apiKey()).getObject("/api/v1/meta", null).optString("mode", ""),
                mode -> {
                    settings.saveMode(mode);
                    applyMode("pune".equals(mode));
                },
                e -> { /* unreachable server: keep the tabs we have; each screen explains the error */ });
    }

    @Override
    protected void onPause() {
        if (detect != null) {
            detect.cancel();
        }
        super.onPause();
    }

    private int startTab(boolean configured) {
        if (!configured) {
            return pune ? R.id.nav_pune_status : R.id.nav_settings;
        }
        return pune ? R.id.nav_pune_home : R.id.nav_live;
    }

    /** Switch between the New York and Pune tabs; called when the server's mode is learned. */
    public void applyMode(boolean nowPune) {
        if (nowPune == pune) {
            return;
        }
        pune = nowPune;
        nav.getMenu().clear();
        nav.inflateMenu(pune ? R.menu.bottom_nav_pune : R.menu.bottom_nav);
        nav.setSelectedItemId(startTab(true));
    }

    @Override
    protected void onSaveInstanceState(@NonNull Bundle out) {
        super.onSaveInstanceState(out);
        out.putInt(KEY_TAB, nav.getSelectedItemId());
    }

    private static Fragment fragmentFor(int id) {
        if (id == R.id.nav_overview) {
            return new OverviewFragment();
        } else if (id == R.id.nav_forecast) {
            return new ForecastFragment();
        } else if (id == R.id.nav_anomalies) {
            return new AnomaliesFragment();
        } else if (id == R.id.nav_settings) {
            return new SettingsFragment();
        } else if (id == R.id.nav_pune_home) {
            return new PuneHomeFragment();
        } else if (id == R.id.nav_pune_map) {
            return new PuneMapFragment();
        } else if (id == R.id.nav_pune_forecast) {
            return new PuneForecastFragment();
        } else if (id == R.id.nav_pune_alerts) {
            return new PuneAlertsFragment();
        } else if (id == R.id.nav_pune_status) {
            return new PuneStatusFragment();
        }
        return new LiveFragment();
    }

    private void show(Fragment f) {
        getSupportFragmentManager().popBackStack(null, androidx.fragment.app.FragmentManager.POP_BACK_STACK_INCLUSIVE);
        getSupportFragmentManager().beginTransaction().replace(R.id.container, f).commit();
    }
}
