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

/**
 * Unit tests for {@link ReportDateUtils}.
 *
 * All formatting assertions use fixed instants (never {@code new Date()}) and are
 * evaluated in UTC, which is the timezone the utility pins its formatters to.
 *
 * Written in JUnit 4 style to match the current stack (JUnit 5 is excluded in pom.xml).
 */
public class ReportDateUtilsTest {

    /** 2024-01-01T00:00:00Z */
    private static final Date EPOCH_2024 = new Date(1_704_067_200_000L);
    /** 2024-03-15T13:45:09Z */
    private static final Date MID_MARCH_2024 = new Date(1_710_510_309_000L);

    private static final long SECOND_MS = 1000L;
    private static final long MINUTE_MS = 60 * SECOND_MS;
    private static final long HOUR_MS = 60 * MINUTE_MS;
    private static final long DAY_MS = 24 * HOUR_MS;

    // ----- toIsoString -----

    @Test
    public void toIsoStringFormatsInUtc() {
        assertEquals("2024-01-01T00:00:00Z", ReportDateUtils.toIsoString(EPOCH_2024));
        assertEquals("2024-03-15T13:45:09Z", ReportDateUtils.toIsoString(MID_MARCH_2024));
    }

    @Test
    public void toIsoStringReturnsNullForNull() {
        assertNull(ReportDateUtils.toIsoString(null));
    }

    // ----- toDisplayString -----

    @Test
    public void toDisplayStringFormatsDayAndTimeInUtc() {
        // The month name is locale-dependent, the rest of the pattern is not.
        String display = ReportDateUtils.toDisplayString(MID_MARCH_2024);
        assertTrue("unexpected display format: " + display,
                display.matches("\\p{L}{3,} 15, 2024 13:45"));
    }

    @Test
    public void toDisplayStringReturnsNaForNull() {
        assertEquals("N/A", ReportDateUtils.toDisplayString(null));
    }

    // ----- toFileNameString -----

    @Test
    public void toFileNameStringUsesCompactUtcStamp() {
        assertEquals("20240315_134509", ReportDateUtils.toFileNameString(MID_MARCH_2024));
    }

    @Test
    public void toFileNameStringFallsBackToNowForNull() {
        String fileStamp = ReportDateUtils.toFileNameString(null);
        assertTrue("unexpected file stamp: " + fileStamp, fileStamp.matches("\\d{8}_\\d{6}"));
    }

    // ----- parseIsoDate -----

    @Test
    public void parseIsoDateAcceptsEverySupportedPattern() {
        assertEquals(EPOCH_2024, ReportDateUtils.parseIsoDate("2024-01-01T00:00:00Z"));
        assertEquals(EPOCH_2024, ReportDateUtils.parseIsoDate("2024-01-01T00:00:00+0000"));
        assertEquals(MID_MARCH_2024, ReportDateUtils.parseIsoDate("2024-03-15T13:45:09Z"));

        // The two patterns without a zone designator are parsed in the default timezone.
        Date parsedLocal = ReportDateUtils.parseIsoDate("2024-03-15 13:45:09");
        assertEquals(localDate(2024, Calendar.MARCH, 15, 13, 45, 9), parsedLocal);
        assertEquals(localDate(2024, Calendar.MARCH, 15, 0, 0, 0),
                ReportDateUtils.parseIsoDate("2024-03-15"));
    }

    @Test
    public void parseIsoDateReturnsNullForBlankInput() {
        assertNull(ReportDateUtils.parseIsoDate(null));
        assertNull(ReportDateUtils.parseIsoDate(""));
        assertNull(ReportDateUtils.parseIsoDate("   "));
    }

    @Test
    public void parseIsoDateRejectsUnparseableInput() {
        try {
            ReportDateUtils.parseIsoDate("not-a-date");
            fail("expected IllegalArgumentException");
        } catch (IllegalArgumentException e) {
            assertTrue(e.getMessage().contains("Cannot parse date: not-a-date"));
        }
    }

    // ----- startOfToday / startOfMonth -----

    @Test
    public void startOfTodayIsMidnightUtcWithinTheLastDay() {
        Date start = ReportDateUtils.startOfToday();
        Calendar cal = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
        cal.setTime(start);

        assertEquals(0, cal.get(Calendar.HOUR_OF_DAY));
        assertEquals(0, cal.get(Calendar.MINUTE));
        assertEquals(0, cal.get(Calendar.SECOND));
        assertEquals(0, cal.get(Calendar.MILLISECOND));

        long age = System.currentTimeMillis() - start.getTime();
        assertTrue("start of today should be in the past 24h, was " + age + "ms ago",
                age >= 0 && age < DAY_MS);
    }

    @Test
    public void startOfMonthIsFirstDayAtMidnightUtc() {
        Date start = ReportDateUtils.startOfMonth();
        Calendar cal = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
        cal.setTime(start);

        assertEquals(1, cal.get(Calendar.DAY_OF_MONTH));
        assertEquals(0, cal.get(Calendar.HOUR_OF_DAY));
        assertEquals(0, cal.get(Calendar.MINUTE));
        assertEquals(0, cal.get(Calendar.SECOND));
        assertEquals(0, cal.get(Calendar.MILLISECOND));

        assertTrue("start of month must not be after start of today",
                !start.after(ReportDateUtils.startOfToday()));
    }

    // ----- daysAgo -----

    @Test
    public void daysAgoSubtractsWholeDays() {
        long tolerance = 2 * HOUR_MS; // absorbs DST shifts and clock drift during the test
        long now = System.currentTimeMillis();

        assertTrue(Math.abs(now - ReportDateUtils.daysAgo(0).getTime()) < tolerance);
        assertTrue(Math.abs((now - 7 * DAY_MS) - ReportDateUtils.daysAgo(7).getTime()) < tolerance);
        assertTrue("daysAgo(30) must be older than daysAgo(7)",
                ReportDateUtils.daysAgo(30).before(ReportDateUtils.daysAgo(7)));
    }

    @Test
    public void daysAgoWithNegativeArgumentReturnsFutureDate() {
        assertTrue(ReportDateUtils.daysAgo(-1).after(new Date()));
    }

    // ----- isWithinRange -----

    @Test
    public void isWithinRangeIsInclusiveOfBothBounds() {
        Date start = EPOCH_2024;
        Date end = MID_MARCH_2024;
        Date middle = new Date((start.getTime() + end.getTime()) / 2);

        assertTrue(ReportDateUtils.isWithinRange(start, start, end));
        assertTrue(ReportDateUtils.isWithinRange(end, start, end));
        assertTrue(ReportDateUtils.isWithinRange(middle, start, end));
    }

    @Test
    public void isWithinRangeRejectsDatesOutsideTheRange() {
        Date start = EPOCH_2024;
        Date end = MID_MARCH_2024;

        assertFalse(ReportDateUtils.isWithinRange(new Date(start.getTime() - 1), start, end));
        assertFalse(ReportDateUtils.isWithinRange(new Date(end.getTime() + 1), start, end));
    }

    @Test
    public void isWithinRangeRejectsAnyNullArgument() {
        assertFalse(ReportDateUtils.isWithinRange(null, EPOCH_2024, MID_MARCH_2024));
        assertFalse(ReportDateUtils.isWithinRange(EPOCH_2024, null, MID_MARCH_2024));
        assertFalse(ReportDateUtils.isWithinRange(EPOCH_2024, MID_MARCH_2024, null));
    }

    // ----- humanReadableDuration -----

    @Test
    public void humanReadableDurationRendersSecondsMinutesAndHours() {
        assertEquals("45s", duration(45 * SECOND_MS));
        assertEquals("2m 5s", duration(2 * MINUTE_MS + 5 * SECOND_MS));
        assertEquals("3h 7m", duration(3 * HOUR_MS + 7 * MINUTE_MS + 30 * SECOND_MS));
    }

    @Test
    public void humanReadableDurationHandlesZeroAndBoundaries() {
        assertEquals("0s", duration(0));
        assertEquals("1m 0s", duration(MINUTE_MS));
        assertEquals("1h 0m", duration(HOUR_MS));
    }

    @Test
    public void humanReadableDurationReturnsUnknownWhenEitherEndIsNull() {
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(null, EPOCH_2024));
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(EPOCH_2024, null));
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(null, null));
    }

    @Test
    public void utilityClassExposesOnlyStaticApi() {
        // Guards the private constructor of the utility class.
        assertNotNull(ReportDateUtils.class.getDeclaredConstructors());
        assertEquals(1, ReportDateUtils.class.getDeclaredConstructors().length);
        assertFalse(ReportDateUtils.class.getDeclaredConstructors()[0].isAccessible());
    }

    private static String duration(long millis) {
        return ReportDateUtils.humanReadableDuration(EPOCH_2024, new Date(EPOCH_2024.getTime() + millis));
    }

    private static Date localDate(int year, int month, int day, int hour, int minute, int second) {
        Calendar cal = Calendar.getInstance();
        cal.clear();
        cal.set(year, month, day, hour, minute, second);
        return cal.getTime();
    }
}
