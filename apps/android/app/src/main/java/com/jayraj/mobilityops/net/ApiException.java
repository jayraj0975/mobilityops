package com.jayraj.mobilityops.net;

import java.io.IOException;

/** A failed request, with the server's own explanation when it sent one. */
public final class ApiException extends IOException {
    public final int status;
    public final String code;

    public ApiException(int status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }

    public boolean isNotReady() {
        return "not_ready".equals(code) || "no_data".equals(code);
    }
}
