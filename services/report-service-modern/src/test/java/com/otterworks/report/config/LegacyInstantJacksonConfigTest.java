package com.otterworks.report.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.report.model.ReportRequest;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.json.JsonTest;
import org.springframework.context.annotation.Import;

import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** The modern service must keep the legacy java.util.Date JSON wire format for Instant fields. */
@JsonTest
@Import(LegacyInstantJacksonConfig.class)
class LegacyInstantJacksonConfigTest {

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void serializesInstantLikeLegacyDate() throws Exception {
        String json = objectMapper.writeValueAsString(Instant.parse("2026-01-31T23:59:59.5Z"));
        assertEquals("\"2026-01-31T23:59:59.500+00:00\"", json);
    }

    @ParameterizedTest
    @CsvSource(delimiter = '|', value = {
            "1767225600000                  | 2026-01-01T00:00:00Z",
            "\"2026-02-01\"                 | 2026-02-01T00:00:00Z",
            "\"2026-01-01T10:00:00Z\"       | 2026-01-01T10:00:00Z",
            "\"2026-01-01T10:00:00.123456+01:00\" | 2026-01-01T09:00:00.123Z",
            "\"Thu, 01 Jan 2026 10:00:00 GMT\" | 2026-01-01T10:00:00Z"
    })
    void deserializesTheInputsLegacyDateAccepted(String jsonValue, String expected) throws Exception {
        String body = "{\"reportName\":\"r\",\"category\":\"AUDIT_LOG\",\"reportType\":\"CSV\","
                + "\"requestedBy\":\"u\",\"dateFrom\":" + jsonValue + "}";
        ReportRequest request = objectMapper.readValue(body, ReportRequest.class);
        assertEquals(Instant.parse(expected), request.dateFrom());
    }
}
