package com.otterworks.report.util;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ReportDateUtilsTest {

    @ParameterizedTest
    @CsvSource({
            "2026-03-04T05:06:07Z,          2026-03-04T05:06:07Z",
            "2026-03-04T05:06:07+0200,      2026-03-04T03:06:07Z",
            "2026-03-04 05:06:07,           2026-03-04T05:06:07Z",
            "2026-03-04,                    2026-03-04T00:00:00Z"
    })
    void parseIsoDateAcceptsLegacyFormatsInUtc(String input, String expected) {
        assertEquals(Instant.parse(expected), ReportDateUtils.parseIsoDate(input));
    }

    @Test
    void parseIsoDateBlankIsNullAndGarbageThrows() {
        assertNull(ReportDateUtils.parseIsoDate(" "));
        assertThrows(IllegalArgumentException.class, () -> ReportDateUtils.parseIsoDate("yesterday"));
    }

    @Test
    void humanReadableDurationMatchesLegacyBuckets() {
        Instant start = Instant.parse("2026-01-01T00:00:00Z");
        assertEquals("42s", ReportDateUtils.humanReadableDuration(start, start.plusSeconds(42)));
        assertEquals("3m 5s", ReportDateUtils.humanReadableDuration(start, start.plusSeconds(185)));
        assertEquals("2h 1m", ReportDateUtils.humanReadableDuration(start, start.plusSeconds(7260)));
        assertEquals("unknown", ReportDateUtils.humanReadableDuration(null, start));
    }

    @Test
    void isWithinRangeIsInclusiveAndNullSafe() {
        Instant start = Instant.parse("2026-01-01T00:00:00Z");
        Instant end = Instant.parse("2026-01-31T00:00:00Z");
        assertTrue(ReportDateUtils.isWithinRange(start, start, end));
        assertTrue(ReportDateUtils.isWithinRange(end, start, end));
        assertFalse(ReportDateUtils.isWithinRange(end.plusMillis(1), start, end));
        assertFalse(ReportDateUtils.isWithinRange(null, start, end));
    }

    @Test
    void daysAgoAndNowAreMillisecondPrecision() {
        assertEquals(0, ReportDateUtils.now().getNano() % 1_000_000);
        assertTrue(ReportDateUtils.daysAgo(30).isBefore(ReportDateUtils.now()));
    }
}
