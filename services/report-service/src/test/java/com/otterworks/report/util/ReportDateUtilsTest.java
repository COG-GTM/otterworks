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
 * All formatting assertions use fixed instants (never {@code new Date()}) and the class
 * formats in UTC, so the expectations are stable regardless of the machine time zone.
 *
 * JUnit 4 to match the service stack (JUnit 5 is excluded in pom.xml).
 */
public class ReportDateUtilsTest {

    /** 2024-01-01T00:00:00Z */
    private static final Date EPOCH_2024 = new Date(1_704_067_200_000L);
    /** 2024-06-15T13:45:30Z */
    private static final Date MID_2024 = new Date(1_718_459_130_000L);

    @Test
    public void toIsoStringFormatsInUtc() {
        assertEquals("2024-01-01T00:00:00Z", ReportDateUtils.toIsoString(EPOCH_2024));
        assertEquals("2024-06-15T13:45:30Z", ReportDateUtils.toIsoString(MID_2024));
    }

    @Test
    public void toIsoStringReturnsNullForNull() {
        assertNull(ReportDateUtils.toIsoString(null));
    }

    @Test
    public void toDisplayStringFormatsHumanReadableUtc() {
        assertEquals("Jan 01, 2024 00:00", ReportDateUtils.toDisplayString(EPOCH_2024));
        assertEquals("Jun 15, 2024 13:45", ReportDateUtils.toDisplayString(MID_2024));
    }

    @Test
    public void toDisplayStringReturnsPlaceholderForNull() {
        assertEquals("N/A", ReportDateUtils.toDisplayString(null));
    }

    @Test
    public void toFileNameStringUsesSortableCompactFormat() {
        assertEquals("20240101_000000", ReportDateUtils.toFileNameString(EPOCH_2024));
        assertEquals("20240615_134530", ReportDateUtils.toFileNameString(MID_2024));
    }

    @Test
    public void toFileNameStringFallsBackToNowForNull() {
        String name = ReportDateUtils.toFileNameString(null);
        assertTrue("expected yyyyMMdd_HHmmss but was: " + name, name.matches("\\d{8}_\\d{6}"));
    }

    @Test
    public void parseIsoDateAcceptsEverySupportedPattern() {
        assertEquals(EPOCH_2024, ReportDateUtils.parseIsoDate("2024-01-01T00:00:00Z"));
        assertEquals(EPOCH_2024, ReportDateUtils.parseIsoDate("2024-01-01T00:00:00+0000"));
        assertNotNull(ReportDateUtils.parseIsoDate("2024-01-01 12:30:00"));
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

    @Test
    public void daysAgoSubtractsWholeDaysFromNow() {
        long before = System.currentTimeMillis();
        Date sevenDaysAgo = ReportDateUtils.daysAgo(7);
        long after = System.currentTimeMillis();

        long sevenDaysMs = 7L * 24 * 60 * 60 * 1000;
        assertTrue(sevenDaysAgo.getTime() >= before - sevenDaysMs);
        assertTrue(sevenDaysAgo.getTime() <= after - sevenDaysMs);
    }

    @Test
    public void daysAgoZeroIsEssentiallyNow() {
        long delta = Math.abs(System.currentTimeMillis() - ReportDateUtils.daysAgo(0).getTime());
        assertTrue("delta was " + delta + "ms", delta < 5000);
    }

    @Test
    public void isWithinRangeIsInclusiveOnBothBounds() {
        assertTrue(ReportDateUtils.isWithinRange(EPOCH_2024, EPOCH_2024, MID_2024));
        assertTrue(ReportDateUtils.isWithinRange(MID_2024, EPOCH_2024, MID_2024));
        assertTrue(ReportDateUtils.isWithinRange(new Date(EPOCH_2024.getTime() + 1000), EPOCH_2024, MID_2024));
    }

    @Test
    public void isWithinRangeRejectsDatesOutsideTheRange() {
        assertFalse(ReportDateUtils.isWithinRange(new Date(EPOCH_2024.getTime() - 1), EPOCH_2024, MID_2024));
        assertFalse(ReportDateUtils.isWithinRange(new Date(MID_2024.getTime() + 1), EPOCH_2024, MID_2024));
    }

    @Test
    public void isWithinRangeRejectsAnyNullArgument() {
        assertFalse(ReportDateUtils.isWithinRange(null, EPOCH_2024, MID_2024));
        assertFalse(ReportDateUtils.isWithinRange(EPOCH_2024, null, MID_2024));
        assertFalse(ReportDateUtils.isWithinRange(EPOCH_2024, EPOCH_2024, null));
    }

    @Test
    public void humanReadableDurationRendersHoursMinutesOrSeconds() {
        Date start = EPOCH_2024;
        assertEquals("2h 5m", ReportDateUtils.humanReadableDuration(start, plusMillis(start, 7_500_000L)));
        assertEquals("3m 20s", ReportDateUtils.humanReadableDuration(start, plusMillis(start, 200_000L)));
        assertEquals("45s", ReportDateUtils.humanReadableDuration(start, plusMillis(start, 45_000L)));
        assertEquals("0s", ReportDateUtils.humanReadableDuration(start, start));
    }

    @Test
    public void humanReadableDurationReturnsUnknownForNulls() {
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(null, EPOCH_2024));
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(EPOCH_2024, null));
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(null, null));
    }

    private static Date plusMillis(Date base, long millis) {
        return new Date(base.getTime() + millis);
    }
}
