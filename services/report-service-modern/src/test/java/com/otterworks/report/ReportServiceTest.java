package com.otterworks.report;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportType;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;

import static org.hamcrest.Matchers.anyOf;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.notNullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class ReportServiceTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void healthEndpointShouldReturnOk() throws Exception {
        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status", is("healthy")))
                .andExpect(jsonPath("$.service", is("report-service")))
                .andExpect(jsonPath("$.version", is("0.1.0")));
    }

    @Test
    void createReportShouldReturnAccepted() throws Exception {
        ReportRequest request = new ReportRequest(
                "Test Usage Report",
                ReportCategory.USAGE_ANALYTICS,
                ReportType.PDF,
                "test-user-001",
                Instant.now().minusMillis(86400000L * 30),
                Instant.now(),
                null);

        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.id", notNullValue()))
                .andExpect(jsonPath("$.reportName", is("Test Usage Report")))
                .andExpect(jsonPath("$.category", is("USAGE_ANALYTICS")))
                .andExpect(jsonPath("$.reportType", is("PDF")))
                // @Async generation may complete before response is serialized
                .andExpect(jsonPath("$.status", anyOf(is("PENDING"), is("GENERATING"), is("COMPLETED"))));
    }

    @Test
    void createCsvReportShouldReturnAccepted() throws Exception {
        ReportRequest request = new ReportRequest(
                "Audit Log Export",
                ReportCategory.AUDIT_LOG,
                ReportType.CSV,
                "test-user-002",
                null,
                null,
                null);

        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.reportType", is("CSV")));
    }

    @Test
    void createExcelReportShouldReturnAccepted() throws Exception {
        ReportRequest request = new ReportRequest(
                "User Activity Summary",
                ReportCategory.USER_ACTIVITY,
                ReportType.EXCEL,
                "test-user-003",
                null,
                null,
                null);

        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.reportType", is("EXCEL")));
    }

    @Test
    void getReportNotFoundShouldReturn404() throws Exception {
        mockMvc.perform(get("/api/v1/reports/99999"))
                .andExpect(status().isNotFound());
    }

    @Test
    void listReportsShouldReturnEmptyList() throws Exception {
        mockMvc.perform(get("/api/v1/reports")
                        .param("userId", "nonexistent-user"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports").isArray())
                .andExpect(jsonPath("$.total", is(0)));
    }

    @Test
    void createReportWithoutNameShouldReturn400() throws Exception {
        ReportRequest request = new ReportRequest(
                null,
                ReportCategory.AUDIT_LOG,
                ReportType.PDF,
                "test-user",
                null,
                null,
                null);
        // Missing reportName — should fail validation

        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void downloadNonExistentReportShouldReturn404() throws Exception {
        mockMvc.perform(get("/api/v1/reports/99999/download"))
                .andExpect(status().isNotFound());
    }
}
