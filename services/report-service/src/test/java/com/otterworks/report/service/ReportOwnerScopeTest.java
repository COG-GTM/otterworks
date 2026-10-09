package com.otterworks.report.service;

import org.junit.Test;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertSame;

public class ReportOwnerScopeTest {

    private static Map<String, Object> row(String key, String userId) {
        Map<String, Object> row = new HashMap<>();
        row.put(key, userId);
        row.put("value", 1);
        return row;
    }

    @Test
    public void scopedReportKeepsOnlyOwnerRows() {
        List<Map<String, Object>> data = new ArrayList<>();
        data.add(row("userId", "alice"));
        data.add(row("userId", "bob"));
        data.add(row("user_id", "alice"));
        data.add(new HashMap<>());

        List<Map<String, Object>> scoped = ReportGenerationWorker.restrictToOwnerScope(
                data, Collections.singletonMap(ReportService.OWNER_SCOPE_PARAM, "alice"));

        assertEquals(2, scoped.size());
        for (Map<String, Object> r : scoped) {
            assertEquals("alice", r.containsKey("userId") ? r.get("userId") : r.get("user_id"));
        }
    }

    @Test
    public void unscopedReportIsUnchanged() {
        List<Map<String, Object>> data = Collections.singletonList(row("userId", "bob"));

        assertSame(data, ReportGenerationWorker.restrictToOwnerScope(data, null));
        assertSame(data, ReportGenerationWorker.restrictToOwnerScope(data, Collections.emptyMap()));
    }
}
