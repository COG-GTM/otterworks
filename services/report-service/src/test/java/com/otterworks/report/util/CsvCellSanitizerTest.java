package com.otterworks.report.util;

import org.junit.Test;

import java.math.BigDecimal;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;

public class CsvCellSanitizerTest {

    @Test
    public void prefixesEveryFormulaTrigger() {
        String[] payloads = {
                "=cmd|'/c calc'!A1",
                "=HYPERLINK(\"https://evil\",\"click\")",
                "+1+cmd|'/c calc'!A1",
                "-2+3",
                "@SUM(1+1)*cmd|'/c calc'!A1",
                "\t=1+1",
                "\r=1+1",
                "\n=1+1",
                "\uFF1D1+1",
                "\uFF0B1",
                "\uFF0D1",
                "\uFF20SUM(A1)"
        };
        for (String payload : payloads) {
            assertEquals("'" + payload, CsvCellSanitizer.sanitize(payload));
        }
    }

    @Test
    public void leavesOrdinaryTextUnchanged() {
        assertEquals("report.pdf", CsvCellSanitizer.sanitize("report.pdf"));
        assertEquals("alice@example.com", CsvCellSanitizer.sanitize("alice@example.com"));
        assertEquals("a=b", CsvCellSanitizer.sanitize("a=b"));
        assertEquals(" =1+1", CsvCellSanitizer.sanitize(" =1+1"));
        assertEquals("# OtterWorks Report: Q3", CsvCellSanitizer.sanitize("# OtterWorks Report: Q3"));
        assertEquals("", CsvCellSanitizer.sanitize(""));
    }

    @Test
    public void nullBecomesEmptyCell() {
        assertEquals("", CsvCellSanitizer.sanitize((String) null));
        assertEquals("", CsvCellSanitizer.sanitize((Object) null));
    }

    @Test
    public void numericValuesAreWrittenAsIs() {
        assertEquals("-5", CsvCellSanitizer.sanitize(Integer.valueOf(-5)));
        assertEquals("-1.25", CsvCellSanitizer.sanitize(new BigDecimal("-1.25")));
        assertEquals("42", CsvCellSanitizer.sanitize(Long.valueOf(42L)));
    }

    @Test
    public void stringsThatLookNumericAreStillEscaped() {
        assertEquals("'-5", CsvCellSanitizer.sanitize((Object) "-5"));
    }

    @Test
    public void sanitizeAllEscapesEachElement() {
        assertArrayEquals(new String[]{"user_id", "'=evil()", ""},
                CsvCellSanitizer.sanitizeAll(new String[]{"user_id", "=evil()", null}));
    }
}
