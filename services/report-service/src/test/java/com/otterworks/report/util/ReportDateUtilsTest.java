package com.otterworks.report.util;

import org.junit.Test;

import java.lang.reflect.Constructor;
import java.util.Calendar;
import java.util.Date;
import java.util.TimeZone;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Unit tests for {@link ReportDateUtils}.
 *
 * All assertions use fixed instants and UTC so the suite is deterministic regardless of the
 * machine's default time zone. No wall-clock output is ever asserted on directly.
 *
 * Written in JUnit 4 style to match the current stack (JUnit 5 is excluded in pom.xml).
 */
public class ReportDateUtilsTest {

    /** 2024-01-01T00:00:00Z */
    private static final Date EPOCH_2024 = new Date(1_704_067_200_000L);

    /** 2024-03-15T13:45:30Z */
    private static final Date MID_MARCH_2024 = new Date(1_710_510_330_000L);

    private static final long ONE_DAY_MS = 24L * 60 * 60 * 1000;

    // ----- toIsoString -----

    @Test
    public void toIsoStringFormatsInUtc() {
        assertEquals("2024-01-01T00:00:00Z", ReportDateUtils.toIsoString(EPOCH_2024));
        assertEquals("2024-03-15T13:45:30Z", ReportDateUtils.toIsoString(MID_MARCH_2024));
    }

    @Test
    public void toIsoStringReturnsNullForNull() {
        assertNull(ReportDateUtils.toIsoString(null));
    }

    // ----- toDisplayString -----

    @Test
    public void toDisplayStringFormatsInUtc() {
        assertEquals("Jan 01, 2024 00:00", ReportDateUtils.toDisplayString(EPOCH_2024));
        assertEquals("Mar 15, 2024 13:45", ReportDateUtils.toDisplayString(MID_MARCH_2024));
    }

    @Test
    public void toDisplayStringReturnsNaForNull() {
        assertEquals("N/A", ReportDateUtils.toDisplayString(null));
    }

    // ----- toFileNameString -----

    @Test
    public void toFileNameStringFormatsInUtc() {
        assertEquals("20240101_000000", ReportDateUtils.toFileNameString(EPOCH_2024));
        assertEquals("20240315_134530", ReportDateUtils.toFileNameString(MID_MARCH_2024));
    }

    @Test
    public void toFileNameStringFallsBackToNowForNull() {
        // The null branch substitutes the current time; assert on the shape, never the value.
        assertTrue(ReportDateUtils.toFileNameString(null).matches("\\d{8}_\\d{6}"));
    }

    // ----- parseIsoDate -----

    @Test
    public void parseIsoDateAcceptsEverySupportedPattern() {
        assertEquals(EPOCH_2024, ReportDateUtils.parseIsoDate("2024-01-01T00:00:00Z"));
        assertEquals(EPOCH_2024, ReportDateUtils.parseIsoDate("2024-01-01T00:00:00+0000"));
        assertNotNull(ReportDateUtils.parseIsoDate("2024-01-01 00:00:00"));
        assertNotNull(ReportDateUtils.parseIsoDate("2024-01-01"));
    }

    @Test
    public void parseIsoDateReturnsNullForBlankInput() {
        assertNull(ReportDateUtils.parseIsoDate(null));
        assertNull(ReportDateUtils.parseIsoDate(""));
        assertNull(ReportDateUtils.parseIsoDate("   "));
    }

    @Test
    public void parseIsoDateRejectsGarbage() {
        try {
            ReportDateUtils.parseIsoDate("not-a-date");
            fail("expected IllegalArgumentException");
        } catch (IllegalArgumentException e) {
            assertTrue(e.getMessage().contains("Cannot parse date: not-a-date"));
        }
    }

    // ----- startOfToday / startOfMonth -----

    @Test
    public void startOfTodayIsMidnightUtc() {
        Calendar cal = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
        cal.setTime(ReportDateUtils.startOfToday());

        assertEquals(0, cal.get(Calendar.HOUR_OF_DAY));
        assertEquals(0, cal.get(Calendar.MINUTE));
        assertEquals(0, cal.get(Calendar.SECOND));
        assertEquals(0, cal.get(Calendar.MILLISECOND));
    }

    @Test
    public void startOfMonthIsFirstDayAtMidnightUtc() {
        Calendar cal = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
        cal.setTime(ReportDateUtils.startOfMonth());

        assertEquals(1, cal.get(Calendar.DAY_OF_MONTH));
        assertEquals(0, cal.get(Calendar.HOUR_OF_DAY));
        assertEquals(0, cal.get(Calendar.MINUTE));
        assertEquals(0, cal.get(Calendar.SECOND));
        assertEquals(0, cal.get(Calendar.MILLISECOND));
    }

    // ----- daysAgo -----

    @Test
    public void daysAgoSubtractsWholeDays() {
        long today = ReportDateUtils.daysAgo(0).getTime();
        long weekAgo = ReportDateUtils.daysAgo(7).getTime();

        // Compare the two offsets rather than an absolute instant, so the clock cannot flake.
        long delta = today - weekAgo;
        assertTrue("expected ~7 days between the two offsets but was " + delta,
                Math.abs(delta - 7 * ONE_DAY_MS) < 5_000);
    }

    // ----- isWithinRange -----

    @Test
    public void isWithinRangeIsInclusiveOfBothBounds() {
        Date start = EPOCH_2024;
        Date end = new Date(EPOCH_2024.getTime() + ONE_DAY_MS);

        assertTrue(ReportDateUtils.isWithinRange(start, start, end));
        assertTrue(ReportDateUtils.isWithinRange(end, start, end));
        assertTrue(ReportDateUtils.isWithinRange(new Date(start.getTime() + 1), start, end));
    }

    @Test
    public void isWithinRangeRejectsDatesOutsideTheBounds() {
        Date start = EPOCH_2024;
        Date end = new Date(EPOCH_2024.getTime() + ONE_DAY_MS);

        assertFalse(ReportDateUtils.isWithinRange(new Date(start.getTime() - 1), start, end));
        assertFalse(ReportDateUtils.isWithinRange(new Date(end.getTime() + 1), start, end));
    }

    @Test
    public void isWithinRangeRejectsAnyNullArgument() {
        Date start = EPOCH_2024;
        Date end = new Date(EPOCH_2024.getTime() + ONE_DAY_MS);

        assertFalse(ReportDateUtils.isWithinRange(null, start, end));
        assertFalse(ReportDateUtils.isWithinRange(start, null, end));
        assertFalse(ReportDateUtils.isWithinRange(start, end, null));
    }

    // ----- humanReadableDuration -----

    @Test
    public void humanReadableDurationRendersHours() {
        Date end = new Date(EPOCH_2024.getTime() + (2 * 60 * 60 + 5 * 60) * 1000L);
        assertEquals("2h 5m", ReportDateUtils.humanReadableDuration(EPOCH_2024, end));
    }

    @Test
    public void humanReadableDurationRendersMinutes() {
        Date end = new Date(EPOCH_2024.getTime() + (3 * 60 + 12) * 1000L);
        assertEquals("3m 12s", ReportDateUtils.humanReadableDuration(EPOCH_2024, end));
    }

    @Test
    public void humanReadableDurationRendersSeconds() {
        Date end = new Date(EPOCH_2024.getTime() + 42_000L);
        assertEquals("42s", ReportDateUtils.humanReadableDuration(EPOCH_2024, end));
    }

    @Test
    public void humanReadableDurationReturnsUnknownForNulls() {
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(null, EPOCH_2024));
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(EPOCH_2024, null));
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(null, null));
    }

    // ----- utility class contract -----

    @Test
    public void constructorIsPrivate() throws Exception {
        Constructor<ReportDateUtils> ctor = ReportDateUtils.class.getDeclaredConstructor();
        assertFalse(ctor.isAccessible());
        ctor.setAccessible(true);
        assertNotNull(ctor.newInstance());
    }
}
