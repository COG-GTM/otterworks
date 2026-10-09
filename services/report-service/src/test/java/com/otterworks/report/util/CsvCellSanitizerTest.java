package com.otterworks.report.util;

import org.junit.Test;

import java.math.BigDecimal;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;

public class CsvCellSanitizerTest {

    @Test
    public void prefixesFormulaTriggerCharacters() {
        assertEquals("'=HYPERLINK(\"http://evil\",\"x\")", CsvCellSanitizer.sanitize("=HYPERLINK(\"http://evil\",\"x\")"));
        assertEquals("'+1+1", CsvCellSanitizer.sanitize("+1+1"));
        assertEquals("'-2+3", CsvCellSanitizer.sanitize("-2+3"));
        assertEquals("'@SUM(A1:A2)", CsvCellSanitizer.sanitize("@SUM(A1:A2)"));
        assertEquals("'\t=1", CsvCellSanitizer.sanitize("\t=1"));
        assertEquals("'\r=1", CsvCellSanitizer.sanitize("\r=1"));
    }

    @Test
    public void leavesOrdinaryTextUnchanged() {
        assertEquals("FILE_UPLOAD", CsvCellSanitizer.sanitize("FILE_UPLOAD"));
        assertEquals("# OtterWorks Report: Q3", CsvCellSanitizer.sanitize("# OtterWorks Report: Q3"));
        assertEquals("a=b", CsvCellSanitizer.sanitize("a=b"));
        assertEquals("", CsvCellSanitizer.sanitize(""));
        assertEquals("", CsvCellSanitizer.sanitize((String) null));
    }

    @Test
    public void objectValuesAreSanitizedButNumbersStayNumeric() {
        assertEquals("", CsvCellSanitizer.sanitize((Object) null));
        assertEquals("-42", CsvCellSanitizer.sanitize(Integer.valueOf(-42)));
        assertEquals("-1.5", CsvCellSanitizer.sanitize(new BigDecimal("-1.5")));
        assertEquals("'-42", CsvCellSanitizer.sanitize((Object) "-42"));
        assertEquals("'=cmd|' /C calc'!A0", CsvCellSanitizer.sanitize((Object) new StringBuilder("=cmd|' /C calc'!A0")));
    }

    @Test
    public void sanitizeAllCoversEveryCell() {
        assertArrayEquals(new String[]{"user_id", "'=evil", ""},
                CsvCellSanitizer.sanitizeAll(new String[]{"user_id", "=evil", null}));
    }
}
