package com.otterworks.report.util;

/**
 * Neutralizes spreadsheet formula injection (CWE-1236) in CSV cells.
 *
 * Excel, LibreOffice and Google Sheets evaluate a cell whose text starts with
 * a formula trigger even when the field is quoted. Any such cell is prefixed
 * with a single quote so it is shown as literal text. Every CSV generator must
 * route cell values through this class.
 */
public final class CsvCellSanitizer {

    static final char ESCAPE_PREFIX = '\'';

    private CsvCellSanitizer() {
    }

    /** Render a cell value for CSV output; {@code null} becomes an empty cell. */
    public static String sanitize(Object value) {
        if (value == null) {
            return "";
        }
        if (value instanceof Number) {
            return value.toString();
        }
        return sanitize(value.toString());
    }

    public static String sanitize(String value) {
        if (value == null || value.isEmpty()) {
            return value == null ? "" : value;
        }
        return needsEscape(value) ? ESCAPE_PREFIX + value : value;
    }

    /** Leading whitespace is skipped because spreadsheet imports may trim it before evaluating. */
    private static boolean needsEscape(String value) {
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (isFormulaTrigger(c)) {
                return true;
            }
            if (!Character.isWhitespace(c) && !Character.isSpaceChar(c)) {
                return false;
            }
        }
        return false;
    }

    public static String[] sanitizeAll(String[] values) {
        String[] out = new String[values.length];
        for (int i = 0; i < values.length; i++) {
            out[i] = sanitize(values[i]);
        }
        return out;
    }

    static boolean isFormulaTrigger(char c) {
        switch (c) {
            case '=':
            case '+':
            case '-':
            case '@':
            case '\t':
            case '\r':
            case '\n':
            case '\uFF1D': // fullwidth =
            case '\uFF0B': // fullwidth +
            case '\uFF0D': // fullwidth -
            case '\uFF20': // fullwidth @
                return true;
            default:
                return false;
        }
    }
}
