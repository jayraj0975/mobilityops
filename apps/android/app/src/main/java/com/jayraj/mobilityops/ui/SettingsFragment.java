package com.jayraj.mobilityops.ui;

import android.content.Context;
import android.text.InputType;
import android.widget.EditText;
import android.widget.TextView;

import androidx.annotation.NonNull;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.textfield.TextInputEditText;
import com.google.android.material.textfield.TextInputLayout;
import com.jayraj.mobilityops.BuildConfig;
import com.jayraj.mobilityops.R;
import com.jayraj.mobilityops.net.ApiClient;
import com.jayraj.mobilityops.util.Settings;

import org.json.JSONArray;
import org.json.JSONObject;

/** Where the server is, and a button that checks it can be reached. */
public final class SettingsFragment extends ScreenFragment {

    @Override
    protected void build(@NonNull Context c) {
        Settings settings = new Settings(c);
        content.addView(Ui.heading(c, "Server"));
        content.addView(Ui.muted(c, "MobilityOps is self-hosted: enter the address of the machine running it. From the "
                + "Android emulator the host computer is http://10.0.2.2:8000; on a phone use the computer's address on "
                + "your network, for example http://192.168.1.20:8000."));

        TextInputLayout urlLayout = new TextInputLayout(c);
        urlLayout.setHint("Server address");
        TextInputEditText url = new TextInputEditText(urlLayout.getContext());
        url.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        url.setSingleLine(true);
        url.setText(settings.serverUrl());
        urlLayout.addView(url);
        content.addView(urlLayout);

        TextInputLayout keyLayout = new TextInputLayout(c);
        keyLayout.setHint("API key (only if the server requires one)");
        TextInputEditText key = new TextInputEditText(keyLayout.getContext());
        key.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        key.setSingleLine(true);
        key.setText(settings.apiKey());
        keyLayout.addView(key);
        content.addView(keyLayout);

        TextView result = Ui.body(c, "");
        MaterialButton save = new MaterialButton(c);
        save.setText("Save and test connection");
        save.setOnClickListener(v -> {
            settings.save(text(url), text(key));
            url.setText(settings.serverUrl());
            result.setText("Checking " + settings.serverUrl() + " …");
            ApiClient api = new ApiClient(settings.serverUrl(), settings.apiKey());
            load(() -> {
                JSONObject meta = api.getObject("/api/v1/meta", null);
                JSONArray services = meta.optJSONArray("services");
                return meta.optString("data_label") + " (" + meta.optString("mode") + " mode), "
                        + meta.optInt("n_zones") + " zones, "
                        + (services == null || services.length() == 0 ? 1 : services.length()) + " service(s), API "
                        + meta.optString("api_version");
            }, ok -> result.setText("Connected: " + ok + "."),
                    e -> result.setText("Could not connect: " + (e.getMessage() == null ? e.toString() : e.getMessage())));
        });
        content.addView(save);
        content.addView(result);

        content.addView(Ui.heading(c, "About"));
        content.addView(Ui.body(c, "MobilityOps " + BuildConfig.VERSION_NAME + ". Demand analytics, forecasts, anomaly "
                + "detection, simulated repositioning scenarios and a live view over NYC taxi data."));
        content.addView(Ui.muted(c, "The Live tab shows a replay of held-out days (labelled REPLAY) beside live Citi Bike "
                + "and weather feeds. Forecasts are estimates, not guarantees; scenarios are simulations."));
    }

    private static String text(EditText e) {
        return e.getText() == null ? "" : e.getText().toString();
    }
}
