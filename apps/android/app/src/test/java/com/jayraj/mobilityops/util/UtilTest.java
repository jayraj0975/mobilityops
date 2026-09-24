package com.jayraj.mobilityops.util;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class UtilTest {

    @Test
    public void numbersAreGroupedAndMissingValuesReadNotAvailable() {
        assertEquals("1,234,568", Fmt.integer(1234567.6));
        assertEquals("n/a", Fmt.integer((Double) null));
        assertEquals("n/a", Fmt.integer(Double.NaN));
        assertEquals("18.7%", Fmt.percent(0.187, 1));
        assertEquals("n/a", Fmt.percent(null, 1));
        assertEquals("+12.3%", Fmt.signedPercent(0.123, 1));
        assertEquals("-4.0%", Fmt.signedPercent(-0.04, 1));
        assertEquals("1,234.50", Fmt.number(1234.5, 2));
    }

    @Test
    public void agesSpeakInSecondsMinutesAndHours() {
        assertEquals("30 s ago", Fmt.age(30));
        assertEquals("5 min ago", Fmt.age(300));
        assertEquals("3 h ago", Fmt.age(3 * 3600));
        assertEquals("0 s ago", Fmt.age(-5));
    }

    @Test
    public void hoursDropTheTAndTheSeconds() {
        assertEquals("2024-11-06 13:00", Fmt.hour("2024-11-06T13:00:00"));
        assertEquals("n/a", Fmt.hour(null));
    }

    @Test
    public void serverAddressesAreNormalised() {
        assertEquals("http://192.168.1.20:8000", Settings.normalizeUrl(" 192.168.1.20:8000/ "));
        assertEquals("https://example.org", Settings.normalizeUrl("https://example.org//"));
        assertEquals(Settings.DEFAULT_URL, Settings.normalizeUrl(""));
        assertEquals(Settings.DEFAULT_URL, Settings.normalizeUrl(null));
    }

    @Test
    public void isoTimestampsParseWithAndWithoutFractionsAndZones() {
        long a = Times.parseIso("2026-09-24T13:09:54+00:00");
        assertEquals(a, Times.parseIso("2026-09-24T13:09:54Z"));
        assertEquals(a, Times.parseIso("2026-09-24T13:09:54.123456+00:00"));
        assertEquals(a, Times.parseIso("2026-09-24T18:39:54+05:30"));
        assertEquals(-1, Times.parseIso("not a time"));
        assertEquals(-1, Times.parseIso(null));
        assertEquals(30, Times.ageSeconds("2026-09-24T13:09:54+00:00", a + 30_000));
        assertEquals(-1, Times.ageSeconds("junk", a));
    }

    @Test
    public void weekOverWeekComparesTheEarlierWeekWithTheLatestNotTheOtherWayRound() {
        String[] w = Times.weekOverWeek("2025-01-01T00:00:00", "2024-01-01T00:00:00");
        assertEquals("2024-12-18", w[0]); // A: the earlier week [Dec 18, Dec 25)
        assertEquals("2024-12-25", w[1]);
        assertEquals("2024-12-25", w[2]); // B: the latest week [Dec 25, Jan 1)
        assertEquals("2025-01-01", w[3]);
        String[] clamped = Times.weekOverWeek("2024-01-05", "2024-01-01");
        assertEquals("2024-01-01", clamped[0]); // never before the start of the data
    }

    @Test
    public void calendarArithmeticCrossesMonthsYearsAndLeapDays() {
        assertEquals("2024-12-24", Times.addDays("2024-12-31", -7));
        assertEquals("2025-01-01", Times.addDays("2024-12-31", 1));
        assertEquals("2024-02-29", Times.addDays("2024-03-01", -1));
        assertEquals("2024-11-06", Times.addDays("2024-11-06T13:00:00", 0));
    }
}
