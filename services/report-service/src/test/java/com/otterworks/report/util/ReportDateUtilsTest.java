package com.otterworks.report.util;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.util.Calendar;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/**
 * Unit tests for {@link ReportDateUtils}.
 *
 * All assertions use fixed instants and UTC so the results never depend on the
 * machine's clock or default time zone.
 *
 * Written in JUnit 4 style to match the current stack.
 */
public class ReportDateUtilsTest {

    private static long calendarDaysBefore(Date reference, int days) {
        Calendar cal = Calendar.getInstance();
        cal.setTime(reference);
        cal.add(Calendar.DAY_OF_MONTH, -days);
        return cal.getTimeInMillis();
    }

    /** 2024-01-02T03:04:05Z */
    private static final Date FIXED = new Date(1704164645000L);

    private Locale originalLocale;

    @Before
    public void pinLocale() {
        // The production display format has no explicit Locale, so the month
        // abbreviation would otherwise depend on the JVM default.
        originalLocale = Locale.getDefault();
        Locale.setDefault(Locale.US);
    }

    @After
    public void restoreLocale() {
        Locale.setDefault(originalLocale);
    }

    @Test
    public void toIsoStringFormatsInUtc() {
        assertEquals("2024-01-02T03:04:05Z", ReportDateUtils.toIsoString(FIXED));
    }

    @Test
    public void toIsoStringReturnsNullForNull() {
        assertNull(ReportDateUtils.toIsoString(null));
    }

    @Test
    public void toDisplayStringFormatsInUtc() {
        assertEquals("Jan 02, 2024 03:04", ReportDateUtils.toDisplayString(FIXED));
    }

    @Test
    public void toDisplayStringReturnsPlaceholderForNull() {
        assertEquals("N/A", ReportDateUtils.toDisplayString(null));
    }

    @Test
    public void toFileNameStringFormatsInUtc() {
        assertEquals("20240102_030405", ReportDateUtils.toFileNameString(FIXED));
    }

    @Test
    public void toFileNameStringFallsBackToNowForNull() {
        String name = ReportDateUtils.toFileNameString(null);
        assertTrue("expected yyyyMMdd_HHmmss but was " + name, name.matches("\\d{8}_\\d{6}"));
    }

    @Test
    public void parseIsoDateAcceptsAllSupportedPatterns() {
        // Only the +0000 pattern carries a real offset; in the others the trailing
        // 'Z' is a literal, so they are parsed in the JVM's default zone.
        assertEquals(FIXED, ReportDateUtils.parseIsoDate("2024-01-02T03:04:05+0000"));

        Calendar cal = Calendar.getInstance();
        cal.clear();
        cal.set(2024, Calendar.JANUARY, 2, 3, 4, 5);
        assertEquals(cal.getTime(), ReportDateUtils.parseIsoDate("2024-01-02T03:04:05Z"));
        assertEquals(cal.getTime(), ReportDateUtils.parseIsoDate("2024-01-02 03:04:05"));

        cal.clear();
        cal.set(2024, Calendar.JANUARY, 2, 0, 0, 0);
        assertEquals(cal.getTime(), ReportDateUtils.parseIsoDate("2024-01-02"));
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
            assertEquals("Cannot parse date: not-a-date", e.getMessage());
        }
    }

    @Test
    public void startOfTodayIsMidnightUtc() {
        Date start = ReportDateUtils.startOfToday();

        Calendar cal = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
        cal.setTime(start);
        assertEquals(0, cal.get(Calendar.HOUR_OF_DAY));
        assertEquals(0, cal.get(Calendar.MINUTE));
        assertEquals(0, cal.get(Calendar.SECOND));
        assertEquals(0, cal.get(Calendar.MILLISECOND));
        assertTrue("start of today must not be in the future", !start.after(new Date()));
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
    }

    @Test
    public void daysAgoSubtractsWholeDays() {
        Date before = new Date();
        Date sevenDaysAgo = ReportDateUtils.daysAgo(7);
        Date after = new Date();

        // Calendar arithmetic keeps the local wall-clock time, so a DST
        // transition inside the window shifts the result by up to an hour.
        assertTrue(sevenDaysAgo.getTime() <= calendarDaysBefore(after, 7) + 1000);
        assertTrue(sevenDaysAgo.getTime() >= calendarDaysBefore(before, 7) - 1000);
    }

    @Test
    public void isWithinRangeIsInclusiveOnBothBounds() {
        Date start = new Date(1000L);
        Date end = new Date(3000L);

        assertTrue(ReportDateUtils.isWithinRange(new Date(2000L), start, end));
        assertTrue(ReportDateUtils.isWithinRange(start, start, end));
        assertTrue(ReportDateUtils.isWithinRange(end, start, end));
        assertFalse(ReportDateUtils.isWithinRange(new Date(999L), start, end));
        assertFalse(ReportDateUtils.isWithinRange(new Date(3001L), start, end));
    }

    @Test
    public void isWithinRangeRejectsNullArguments() {
        Date start = new Date(1000L);
        Date end = new Date(3000L);

        assertFalse(ReportDateUtils.isWithinRange(null, start, end));
        assertFalse(ReportDateUtils.isWithinRange(new Date(2000L), null, end));
        assertFalse(ReportDateUtils.isWithinRange(new Date(2000L), start, null));
    }

    @Test
    public void humanReadableDurationUsesHoursMinutesOrSeconds() {
        Date base = new Date(0L);

        assertEquals("2h 5m", ReportDateUtils.humanReadableDuration(base, new Date(7500000L)));
        assertEquals("3m 20s", ReportDateUtils.humanReadableDuration(base, new Date(200000L)));
        assertEquals("45s", ReportDateUtils.humanReadableDuration(base, new Date(45000L)));
        assertEquals("0s", ReportDateUtils.humanReadableDuration(base, base));
    }

    @Test
    public void humanReadableDurationIsUnknownWhenEitherEndpointIsNull() {
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(null, new Date(1000L)));
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(new Date(1000L), null));
    }
}
