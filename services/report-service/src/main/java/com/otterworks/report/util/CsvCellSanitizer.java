package com.otterworks.report.util;

/**
 * Neutralizes CSV cells that a spreadsheet would otherwise evaluate as a formula
 * (CWE-1236). Quoting a field does not stop Excel, LibreOffice or Sheets from
 * evaluating it, so any text cell starting with a formula trigger is prefixed
 * with a single quote, which makes the spreadsheet render it as literal text.
 */
public final class CsvCellSanitizer {

    private static final String FORMULA_TRIGGERS = "=+-@\t\r";

    private CsvCellSanitizer() {
    }

    public static String sanitize(String cell) {
        if (cell == null) {
            return "";
        }
        if (!cell.isEmpty() && FORMULA_TRIGGERS.indexOf(cell.charAt(0)) >= 0) {
            return "'" + cell;
        }
        return cell;
    }

    /**
     * Numbers are written as-is so negative values stay numeric; everything else
     * is rendered with {@code toString()} and sanitized.
     */
    public static String sanitize(Object value) {
        if (value == null) {
            return "";
        }
        if (value instanceof Number) {
            return value.toString();
        }
        return sanitize(value.toString());
    }

    public static String[] sanitizeAll(String[] cells) {
        String[] sanitized = new String[cells.length];
        for (int i = 0; i < cells.length; i++) {
            sanitized[i] = sanitize(cells[i]);
        }
        return sanitized;
    }
}
