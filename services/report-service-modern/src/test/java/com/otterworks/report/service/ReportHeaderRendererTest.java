package com.otterworks.report.service;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Properties;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

class ReportHeaderRendererTest {

    private final ReportHeaderRenderer renderer = new ReportHeaderRenderer(new Properties());

    @Test
    void rendersReportVariables() {
        assertEquals("# OtterWorks Report: Quarterly Usage",
                renderer.title(vars("reportName", "Quarterly Usage")));
    }

    @Test
    void rendersRowCount() {
        assertEquals("# Rows: 42", renderer.rows(vars("rows", "42")));
    }

    @Test
    void rendersPeriodFromTwoVariables() {
        Map<String, String> vars = vars("periodFrom", "2026-01-01");
        vars.put("periodTo", "2026-03-31");
        assertEquals("# Period: 2026-01-01 to 2026-03-31", renderer.period(vars));
    }

    @Test
    void undefinedVariableFailsInsteadOfLeakingPlaceholder() {
        try {
            renderer.renderBanner("# ${notProvided}", new LinkedHashMap<String, String>());
            fail("expected an undefined banner variable to be rejected");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("notProvided"), "message should name the variable");
        }
    }

    @Test
    void reportNameContainingATokenIsInsertedLiterally() {
        assertEquals("# OtterWorks Report: Q1 ${cost} review",
                renderer.title(vars("reportName", "Q1 ${cost} review")));
    }

    private Map<String, String> vars(String key, String value) {
        Map<String, String> vars = new LinkedHashMap<String, String>();
        vars.put(key, value);
        return vars;
    }
}
