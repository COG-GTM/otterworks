package com.otterworks.report.service;

import org.junit.Test;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;

public class ReportDataFetcherScopeTest {

    @Test
    public void restrictToUserKeepsOnlyThatUsersRows() {
        List<Map<String, Object>> data = new ArrayList<>();
        data.add(row("userId", "alice"));
        data.add(row("userId", "mallory"));
        data.add(row("user_id", "mallory"));
        data.add(row("user_id", "bob"));
        data.add(row("event_type", "no-user"));

        List<Map<String, Object>> scoped = ReportDataFetcher.restrictToUser(data, "mallory");

        assertEquals(2, scoped.size());
        assertEquals("mallory", scoped.get(0).get("userId"));
        assertEquals("mallory", scoped.get(1).get("user_id"));
    }

    private static Map<String, Object> row(String key, String value) {
        Map<String, Object> row = new HashMap<>();
        row.put(key, value);
        return row;
    }
}
