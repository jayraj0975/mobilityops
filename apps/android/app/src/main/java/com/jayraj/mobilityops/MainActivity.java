package com.jayraj.mobilityops;

import android.os.Bundle;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.fragment.app.Fragment;

import com.google.android.material.bottomnavigation.BottomNavigationView;
import com.jayraj.mobilityops.ui.AnomaliesFragment;
import com.jayraj.mobilityops.ui.ForecastFragment;
import com.jayraj.mobilityops.ui.LiveFragment;
import com.jayraj.mobilityops.ui.OverviewFragment;
import com.jayraj.mobilityops.ui.SettingsFragment;
import com.jayraj.mobilityops.util.Settings;

/** One activity, five tabs. A fresh install opens on Settings so the server address is set first. */
public final class MainActivity extends AppCompatActivity {
    private static final String KEY_TAB = "tab";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        BottomNavigationView nav = findViewById(R.id.bottom_nav);
        nav.setOnItemSelectedListener(item -> {
            show(fragmentFor(item.getItemId()));
            return true;
        });
        if (savedInstanceState == null) {
            nav.setSelectedItemId(new Settings(this).isConfigured() ? R.id.nav_live : R.id.nav_settings);
        } else {
            nav.setSelectedItemId(savedInstanceState.getInt(KEY_TAB, R.id.nav_live));
        }
    }

    @Override
    protected void onSaveInstanceState(@NonNull Bundle out) {
        super.onSaveInstanceState(out);
        out.putInt(KEY_TAB, ((BottomNavigationView) findViewById(R.id.bottom_nav)).getSelectedItemId());
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
        }
        return new LiveFragment();
    }

    private void show(Fragment f) {
        getSupportFragmentManager().beginTransaction().replace(R.id.container, f).commit();
    }
}
