package com.jayraj.mobilityops.ui;

import android.content.Context;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.ScrollView;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;
import androidx.fragment.app.Fragment;

import com.jayraj.mobilityops.R;
import com.jayraj.mobilityops.net.ApiClient;
import com.jayraj.mobilityops.net.ApiException;
import com.jayraj.mobilityops.util.Async;
import com.jayraj.mobilityops.util.Settings;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;

/** Base for every screen: a scrolling column, the API client, and lifecycle-safe background calls. */
public abstract class ScreenFragment extends Fragment {
    protected LinearLayout content;
    private final List<Async.Task> tasks = new ArrayList<>();

    /** Fill {@link #content}; called each time the view is (re)created. */
    protected abstract void build(@NonNull Context context);

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container, @Nullable Bundle state) {
        Context c = requireContext();
        ScrollView scroll = new ScrollView(c);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(ContextCompat.getColor(c, R.color.bg));
        content = new LinearLayout(c);
        content.setOrientation(LinearLayout.VERTICAL);
        int pad = Ui.dp(c, 16);
        content.setPadding(pad, pad, pad, pad);
        scroll.addView(content, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        build(c);
        return scroll;
    }

    @Override
    public void onDestroyView() {
        for (Async.Task t : tasks) {
            t.cancel();
        }
        tasks.clear();
        content = null;
        super.onDestroyView();
    }

    protected ApiClient api() {
        Settings s = new Settings(requireContext());
        return new ApiClient(s.serverUrl(), s.apiKey());
    }

    /** Run a blocking call off the main thread; results never reach a destroyed screen. */
    protected <T> void load(Callable<T> work, Async.Callback<T> ok, Async.Failure fail) {
        tasks.add(Async.run(work, ok, fail));
    }

    /** A short, honest error block with a retry button. */
    protected View errorView(Context c, Exception e, Runnable retry) {
        LinearLayout box = new LinearLayout(c);
        box.setOrientation(LinearLayout.VERTICAL);
        boolean notReady = e instanceof ApiException && ((ApiException) e).isNotReady();
        String title = notReady ? "Not generated yet" : "Something went wrong";
        String detail = e.getMessage() == null ? "Unknown error." : e.getMessage();
        if (!notReady && !(e instanceof ApiException)) {
            detail += " Check the server address in Settings and that the server is running.";
        }
        box.addView(Ui.banner(c, title, detail, R.color.surface, notReady ? R.color.border : R.color.fail));
        com.google.android.material.button.MaterialButton retryButton = new com.google.android.material.button.MaterialButton(c);
        retryButton.setText("Try again");
        retryButton.setOnClickListener(v -> retry.run());
        box.addView(retryButton);
        return box;
    }
}
