package com.otterworks.report.qa;

import com.otterworks.report.util.ReportDateUtils;
import org.junit.Ignore;
import org.junit.Test;

import java.util.Date;
import java.util.TimeZone;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/** QA audit: date helpers used for report ranges and file names. */
public class QaReportDateUtilsTest {

    private static final long JAN1 = 1_767_225_600_000L; // 2026-01-01T00:00:00Z

    @Test
    public void isWithinRangeIsInclusiveAndNullSafe() {
        Date start = new Date(JAN1);
        Date end = new Date(JAN1 + 1000);
        assertTrue(ReportDateUtils.isWithinRange(start, start, end));
        assertTrue(ReportDateUtils.isWithinRange(end, start, end));
        assertFalse(ReportDateUtils.isWithinRange(new Date(JAN1 - 1), start, end));
        assertFalse(ReportDateUtils.isWithinRange(new Date(JAN1 + 1001), start, end));
        assertFalse(ReportDateUtils.isWithinRange(null, start, end));
        assertFalse(ReportDateUtils.isWithinRange(start, null, end));
        assertFalse(ReportDateUtils.isWithinRange(start, start, null));
    }

    @Test
    public void isWithinRangeIsAlwaysFalseForInvertedRange() {
        assertFalse(ReportDateUtils.isWithinRange(new Date(JAN1), new Date(JAN1 + 10), new Date(JAN1 - 10)));
    }

    @Test
    public void formatsInUtc() {
        assertEquals("2026-01-01T00:00:00Z", ReportDateUtils.toIsoString(new Date(JAN1)));
        assertEquals("20260101_000000", ReportDateUtils.toFileNameString(new Date(JAN1)));
    }

    @Test
    public void parseIsoDateHandlesBlankAndRejectsGarbage() {
        assertNull(ReportDateUtils.parseIsoDate(""));
        assertNull(ReportDateUtils.parseIsoDate(null));
        try {
            ReportDateUtils.parseIsoDate("31/12/2026");
            throw new AssertionError("expected IllegalArgumentException");
        } catch (IllegalArgumentException expected) {
            // ok
        }
    }

    @Ignore("Finding RPT-5: parseIsoDate treats the trailing 'Z' as a literal and parses in the JVM default zone, "
            + "so toIsoString/parseIsoDate do not round-trip outside UTC")
    @Test
    public void parseIsoDateRoundTripsInNonUtcZone() {
        TimeZone original = TimeZone.getDefault();
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("Asia/Tokyo"));
            assertEquals(JAN1, ReportDateUtils.parseIsoDate("2026-01-01T00:00:00Z").getTime());
        } finally {
            TimeZone.setDefault(original);
        }
    }

    @Test
    public void humanReadableDuration() {
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(null, new Date()));
        assertEquals("5s", ReportDateUtils.humanReadableDuration(new Date(0), new Date(5_000)));
        assertEquals("2m 5s", ReportDateUtils.humanReadableDuration(new Date(0), new Date(125_000)));
        assertEquals("1h 1m", ReportDateUtils.humanReadableDuration(new Date(0), new Date(3_660_000)));
    }

    @Test
    public void daysAgoMovesBackwards() {
        long diff = System.currentTimeMillis() - ReportDateUtils.daysAgo(30).getTime();
        assertTrue(Math.abs(diff - 30L * 86_400_000L) < 3_700_000L);
    }
}
