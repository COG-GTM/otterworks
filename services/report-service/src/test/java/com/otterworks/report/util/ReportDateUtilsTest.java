package com.otterworks.report.util;

import org.junit.Test;

import java.util.Calendar;
import java.util.Date;
import java.util.TimeZone;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

public class ReportDateUtilsTest {

    private static final Date EPOCH_PLUS = new Date(1705312800000L); // 2024-01-15T10:00:00Z

    @Test
    public void toIsoStringFormatsInUtc() {
        assertEquals("2024-01-15T10:00:00Z", ReportDateUtils.toIsoString(EPOCH_PLUS));
        assertNull(ReportDateUtils.toIsoString(null));
    }

    @Test
    public void toDisplayStringFormatsInUtcAndHandlesNull() {
        assertEquals("Jan 15, 2024 10:00", ReportDateUtils.toDisplayString(EPOCH_PLUS));
        assertEquals("N/A", ReportDateUtils.toDisplayString(null));
    }

    @Test
    public void toFileNameStringFormatsAndDefaultsToNow() {
        assertEquals("20240115_100000", ReportDateUtils.toFileNameString(EPOCH_PLUS));
        String now = ReportDateUtils.toFileNameString(null);
        assertTrue(now, now.matches("\\d{8}_\\d{6}"));
    }

    @Test
    public void parseIsoDateHandlesBlankAndSupportedPatterns() {
        assertNull(ReportDateUtils.parseIsoDate(null));
        assertNull(ReportDateUtils.parseIsoDate("  "));
        assertNotNull(ReportDateUtils.parseIsoDate("2024-01-15T10:00:00Z"));
        assertEquals(EPOCH_PLUS, ReportDateUtils.parseIsoDate("2024-01-15T10:00:00+0000"));
        assertEquals(ReportDateUtils.parseIsoDate("2024-01-15 00:00:00"),
                ReportDateUtils.parseIsoDate("2024-01-15"));
    }

    @Test
    public void parseIsoDateRejectsGarbage() {
        try {
            ReportDateUtils.parseIsoDate("not-a-date");
            fail("expected IllegalArgumentException");
        } catch (IllegalArgumentException e) {
            assertTrue(e.getMessage().contains("not-a-date"));
        }
    }

    @Test
    public void startOfTodayIsUtcMidnight() {
        Calendar cal = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
        cal.setTime(ReportDateUtils.startOfToday());
        assertEquals(0, cal.get(Calendar.HOUR_OF_DAY));
        assertEquals(0, cal.get(Calendar.MINUTE));
        assertEquals(0, cal.get(Calendar.SECOND));
        assertEquals(0, cal.get(Calendar.MILLISECOND));
        assertFalse(ReportDateUtils.startOfToday().after(new Date()));
    }

    @Test
    public void startOfMonthIsFirstDayAtUtcMidnight() {
        Calendar cal = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
        cal.setTime(ReportDateUtils.startOfMonth());
        assertEquals(1, cal.get(Calendar.DAY_OF_MONTH));
        assertEquals(0, cal.get(Calendar.HOUR_OF_DAY));
        assertEquals(0, cal.get(Calendar.MILLISECOND));
        assertFalse(ReportDateUtils.startOfMonth().after(ReportDateUtils.startOfToday()));
    }

    @Test
    public void daysAgoSubtractsDays() {
        long diff = System.currentTimeMillis() - ReportDateUtils.daysAgo(3).getTime();
        assertTrue(diff >= 3L * 86400000L - 1000 && diff <= 3L * 86400000L + 60000);
    }

    @Test
    public void isWithinRangeIsInclusiveAndNullSafe() {
        Date start = new Date(1000);
        Date end = new Date(2000);
        assertTrue(ReportDateUtils.isWithinRange(new Date(1500), start, end));
        assertTrue(ReportDateUtils.isWithinRange(start, start, end));
        assertTrue(ReportDateUtils.isWithinRange(end, start, end));
        assertFalse(ReportDateUtils.isWithinRange(new Date(999), start, end));
        assertFalse(ReportDateUtils.isWithinRange(new Date(2001), start, end));
        assertFalse(ReportDateUtils.isWithinRange(null, start, end));
        assertFalse(ReportDateUtils.isWithinRange(start, null, end));
        assertFalse(ReportDateUtils.isWithinRange(start, start, null));
    }

    @Test
    public void humanReadableDurationCoversEachUnit() {
        Date start = new Date(0);
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(null, start));
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(start, null));
        assertEquals("42s", ReportDateUtils.humanReadableDuration(start, new Date(42_000)));
        assertEquals("2m 5s", ReportDateUtils.humanReadableDuration(start, new Date(125_000)));
        assertEquals("1h 1m", ReportDateUtils.humanReadableDuration(start, new Date(3_660_000)));
    }
}
