package com.jayraj.mobilityops.net;

import java.util.ArrayList;
import java.util.List;

/**
 * Incremental parser for server-sent events. Feed it text as it arrives; it returns every event
 * that is complete and keeps the unfinished tail for the next call. Comment lines (": keep-alive")
 * are ignored and multi-line data is joined with newlines.
 */
public final class SseParser {

    /** One complete event. */
    public static final class Event {
        public final String name;
        public final String data;

        Event(String name, String data) {
            this.name = name;
            this.data = data;
        }
    }

    private final StringBuilder buffer = new StringBuilder();

    public List<Event> feed(String chunk) {
        buffer.append(chunk);
        String text = buffer.toString().replace("\r\n", "\n");
        List<Event> events = new ArrayList<>();
        int end;
        while ((end = text.indexOf("\n\n")) != -1) {
            String block = text.substring(0, end);
            text = text.substring(end + 2);
            String name = "message";
            StringBuilder data = null;
            for (String line : block.split("\n", -1)) {
                if (line.startsWith(":")) {
                    continue;
                }
                if (line.startsWith("event:")) {
                    name = line.substring(6).trim();
                } else if (line.startsWith("data:")) {
                    String value = line.substring(5);
                    if (value.startsWith(" ")) {
                        value = value.substring(1);
                    }
                    if (data == null) {
                        data = new StringBuilder(value);
                    } else {
                        data.append('\n').append(value);
                    }
                }
            }
            if (data != null) {
                events.add(new Event(name, data.toString()));
            }
        }
        buffer.setLength(0);
        buffer.append(text);
        return events;
    }
}
