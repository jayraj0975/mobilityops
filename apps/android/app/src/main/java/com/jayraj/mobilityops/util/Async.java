package com.jayraj.mobilityops.util;

import android.os.Handler;
import android.os.Looper;

import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** Run blocking work off the main thread and deliver the result on it, unless cancelled. */
public final class Async {
    private static final ExecutorService POOL = Executors.newFixedThreadPool(4);
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private Async() {}

    public interface Callback<T> {
        void onResult(T value);
    }

    public interface Failure {
        void onError(Exception error);
    }

    /** Call {@link #cancel()} when the screen goes away; a cancelled task never touches the UI. */
    public static final class Task {
        private final AtomicBoolean cancelled = new AtomicBoolean(false);

        public void cancel() {
            cancelled.set(true);
        }
    }

    public static <T> Task run(Callable<T> work, Callback<T> ok, Failure fail) {
        Task task = new Task();
        POOL.execute(() -> {
            try {
                T value = work.call();
                MAIN.post(() -> {
                    if (!task.cancelled.get()) {
                        ok.onResult(value);
                    }
                });
            } catch (Exception e) {
                MAIN.post(() -> {
                    if (!task.cancelled.get()) {
                        fail.onError(e);
                    }
                });
            }
        });
        return task;
    }

    public static void onMain(Runnable r) {
        MAIN.post(r);
    }
}
