package com.otterworks.report.util;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Locale;

/** Thread-safe {@code java.time} replacements for the legacy SimpleDateFormat/Calendar helpers (all UTC). */
public final class ReportDateUtils {

    private static final DateTimeFormatter ISO_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.ROOT).withZone(ZoneOffset.UTC);
    private static final DateTimeFormatter DISPLAY_FORMAT =
            DateTimeFormatter.ofPattern("MMM dd, yyyy HH:mm", Locale.US).withZone(ZoneOffset.UTC);
    private static final DateTimeFormatter FILE_NAME_FORMAT =
            DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss", Locale.ROOT).withZone(ZoneOffset.UTC);

    private static final List<DateTimeFormatter> OFFSET_PARSE_FORMATS = List.of(
            DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.ROOT).withZone(ZoneOffset.UTC),
            DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssxx", Locale.ROOT));
    private static final DateTimeFormatter LOCAL_DATE_TIME_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss", Locale.ROOT);

    private ReportDateUtils() {
    }

    public static String toIsoString(Instant instant) {
        return instant == null ? null : ISO_FORMAT.format(instant);
    }

    public static String toDisplayString(Instant instant) {
        return instant == null ? "N/A" : DISPLAY_FORMAT.format(instant);
    }

    public static String toFileNameString(Instant instant) {
        return FILE_NAME_FORMAT.format(instant == null ? Instant.now() : instant);
    }

    public static Instant parseIsoDate(String dateString) {
        if (dateString == null || dateString.isBlank()) {
            return null;
        }
        for (DateTimeFormatter formatter : OFFSET_PARSE_FORMATS) {
            try {
                return formatter.parse(dateString, Instant::from);
            } catch (DateTimeParseException ignored) {
                // try next pattern
            }
        }
        try {
            return LocalDateTime.parse(dateString, LOCAL_DATE_TIME_FORMAT).toInstant(ZoneOffset.UTC);
        } catch (DateTimeParseException ignored) {
            // try date-only
        }
        try {
            return LocalDate.parse(dateString).atStartOfDay(ZoneOffset.UTC).toInstant();
        } catch (DateTimeParseException e) {
            throw new IllegalArgumentException("Cannot parse date: " + dateString, e);
        }
    }

    public static Instant startOfToday() {
        return LocalDate.now(ZoneOffset.UTC).atStartOfDay(ZoneOffset.UTC).toInstant();
    }

    public static Instant startOfMonth() {
        return LocalDate.now(ZoneOffset.UTC).withDayOfMonth(1).atStartOfDay(ZoneOffset.UTC).toInstant();
    }

    public static Instant daysAgo(int days) {
        return now().minus(days, ChronoUnit.DAYS);
    }

    /** Current instant at millisecond precision, matching what java.util.Date could represent. */
    public static Instant now() {
        return Instant.now().truncatedTo(ChronoUnit.MILLIS);
    }

    public static boolean isWithinRange(Instant instant, Instant start, Instant end) {
        if (instant == null || start == null || end == null) {
            return false;
        }
        return !instant.isBefore(start) && !instant.isAfter(end);
    }

    public static String humanReadableDuration(Instant start, Instant end) {
        if (start == null || end == null) {
            return "unknown";
        }
        Duration duration = Duration.between(start, end);
        long hours = duration.toHours();
        long minutes = duration.toMinutes();
        long seconds = duration.toSeconds();
        if (hours > 0) {
            return hours + "h " + duration.toMinutesPart() + "m";
        } else if (minutes > 0) {
            return minutes + "m " + duration.toSecondsPart() + "s";
        }
        return seconds + "s";
    }
}
