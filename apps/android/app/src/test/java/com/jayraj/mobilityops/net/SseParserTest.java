package com.jayraj.mobilityops.net;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.util.List;

import org.junit.Test;

public class SseParserTest {

    @Test
    public void returnsCompleteEventsAndKeepsTheUnfinishedTail() {
        SseParser p = new SseParser();
        List<SseParser.Event> first = p.feed("event: replay\ndata: {\"a\":1}\n\nevent: fe");
        assertEquals(1, first.size());
        assertEquals("replay", first.get(0).name);
        assertEquals("{\"a\":1}", first.get(0).data);
        List<SseParser.Event> second = p.feed("ed\ndata: {\"b\":2}\n\n");
        assertEquals(1, second.size());
        assertEquals("feed", second.get(0).name);
    }

    @Test
    public void ignoresKeepAliveCommentsJoinsMultiLineDataAndAcceptsCrlf() {
        SseParser p = new SseParser();
        List<SseParser.Event> events = p.feed(": keep-alive\n\nevent: x\r\ndata: one\r\ndata: two\r\n\r\n");
        assertEquals(1, events.size());
        assertEquals("one\ntwo", events.get(0).data);
    }

    @Test
    public void aBlockWithoutDataIsNotAnEventAndDefaultNameIsMessage() {
        SseParser p = new SseParser();
        assertTrue(p.feed("event: empty\n\n").isEmpty());
        assertEquals("message", p.feed("data: hi\n\n").get(0).name);
    }

    @Test
    public void aCarriageReturnSplitAcrossChunksStillParses() {
        SseParser p = new SseParser();
        assertTrue(p.feed("event: a\r").isEmpty());
        List<SseParser.Event> events = p.feed("\ndata: 1\r\n\r\n");
        assertEquals(1, events.size());
        assertEquals("a", events.get(0).name);
    }
}
