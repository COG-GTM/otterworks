package com.otterworks.report.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportType;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.hamcrest.Matchers.anyOf;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.notNullValue;
import static org.hamcrest.Matchers.nullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class ReportControllerIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    // ---- POST /api/v1/reports ----

    @Test
    void createPdfReportReturns202WithCorrectBody() throws Exception {
        ReportRequest request = buildRequest("Integration PDF Report",
                ReportCategory.USAGE_ANALYTICS, ReportType.PDF, "integration-user-1");

        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isAccepted())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.id", notNullValue()))
                .andExpect(jsonPath("$.reportName", is("Integration PDF Report")))
                .andExpect(jsonPath("$.category", is("USAGE_ANALYTICS")))
                .andExpect(jsonPath("$.reportType", is("PDF")))
                .andExpect(jsonPath("$.requestedBy", is("integration-user-1")))
                .andExpect(jsonPath("$.status",
                        anyOf(is("PENDING"), is("GENERATING"), is("COMPLETED"))));
    }

    @Test
    void createCsvReportReturns202() throws Exception {
        ReportRequest request = buildRequest("Integration CSV Report",
                ReportCategory.AUDIT_LOG, ReportType.CSV, "integration-user-2");

        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.reportType", is("CSV")))
                .andExpect(jsonPath("$.category", is("AUDIT_LOG")));
    }

    @Test
    void createExcelReportReturns202() throws Exception {
        ReportRequest request = buildRequest("Integration Excel Report",
                ReportCategory.STORAGE_SUMMARY, ReportType.EXCEL, "integration-user-3");

        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.reportType", is("EXCEL")))
                .andExpect(jsonPath("$.category", is("STORAGE_SUMMARY")));
    }

    @Test
    void createReportWithoutNameReturns400() throws Exception {
        ReportRequest request = new ReportRequest(
                null,
                ReportCategory.COMPLIANCE,
                ReportType.PDF,
                "integration-user-4",
                null,
                null,
                null);

        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void createReportWithoutCategoryReturns400() throws Exception {
        ReportRequest request = new ReportRequest(
                "Missing Category Report",
                null,
                ReportType.CSV,
                "integration-user-5",
                null,
                null,
                null);

        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());
    }

    @Test
    void createReportWithoutTypeReturns400() throws Exception {
        ReportRequest request = new ReportRequest(
                "Missing Type Report",
                ReportCategory.USER_ACTIVITY,
                null,
                "integration-user-6",
                null,
                null,
                null);

        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());
    }

    // ---- GET /api/v1/reports/{id} ----

    @Test
    void getReportByIdReturnsCreatedReport() throws Exception {
        Long id = createReportAndReturnId("Fetch By Id Report",
                ReportCategory.SYSTEM_HEALTH, ReportType.PDF, "integration-user-7");

        mockMvc.perform(get("/api/v1/reports/" + id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id", is(id.intValue())))
                .andExpect(jsonPath("$.reportName", is("Fetch By Id Report")))
                .andExpect(jsonPath("$.category", is("SYSTEM_HEALTH")));
    }

    @Test
    void getNonExistentReportReturns404() throws Exception {
        mockMvc.perform(get("/api/v1/reports/999999"))
                .andExpect(status().isNotFound());
    }

    // ---- GET /api/v1/reports ----

    @Test
    void listReportsByUserIdReturnsArray() throws Exception {
        String userId = "list-test-user-" + System.currentTimeMillis();
        createReportAndReturnId("List Test 1", ReportCategory.AUDIT_LOG,
                ReportType.CSV, userId);
        createReportAndReturnId("List Test 2", ReportCategory.AUDIT_LOG,
                ReportType.PDF, userId);

        mockMvc.perform(get("/api/v1/reports").param("userId", userId))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports").isArray())
                .andExpect(jsonPath("$.total").isNumber());
    }

    @Test
    void listReportsForUnknownUserReturnsEmptyArray() throws Exception {
        mockMvc.perform(get("/api/v1/reports")
                        .param("userId", "nonexistent-user-xyz"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports").isArray())
                .andExpect(jsonPath("$.total", is(0)));
    }

    @Test
    void listReportsByStatusReturnsArray() throws Exception {
        mockMvc.perform(get("/api/v1/reports").param("status", "COMPLETED"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports").isArray());
    }

    // ---- GET /api/v1/reports/{id}/download ----

    @Test
    void downloadNonExistentReportReturns404() throws Exception {
        mockMvc.perform(get("/api/v1/reports/999999/download"))
                .andExpect(status().isNotFound());
    }

    @Test
    void downloadPendingReportReturns409() throws Exception {
        Long id = createReportAndReturnId("Download Pending Report",
                ReportCategory.USAGE_ANALYTICS, ReportType.PDF, "integration-user-8");

        MvcResult download = mockMvc.perform(get("/api/v1/reports/" + id + "/download"))
                .andReturn();

        // Status is read after the download so it cannot go stale in the wrong direction:
        // generation only moves forward, so a report still pending here was pending during
        // the download too.
        MvcResult result = mockMvc.perform(get("/api/v1/reports/" + id))
                .andReturn();
        String statusVal = objectMapper.readTree(
                result.getResponse().getContentAsString()).get("status").asText();

        if ("PENDING".equals(statusVal) || "GENERATING".equals(statusVal)) {
            assertEquals(HttpStatus.CONFLICT.value(), download.getResponse().getStatus());
        }
    }

    // ---- DELETE /api/v1/reports/{id} ----

    @Test
    void deleteExistingReportReturns204() throws Exception {
        Long id = createReportAndReturnId("Delete Me Report",
                ReportCategory.COLLABORATION_METRICS, ReportType.CSV, "integration-user-9");

        mockMvc.perform(delete("/api/v1/reports/" + id))
                .andExpect(status().isNoContent());

        mockMvc.perform(get("/api/v1/reports/" + id))
                .andExpect(status().isNotFound());
    }

    @Test
    void deleteNonExistentReportReturns404() throws Exception {
        mockMvc.perform(delete("/api/v1/reports/999999"))
                .andExpect(status().isNotFound());
    }

    // ---- Health endpoint ----

    @Test
    void healthEndpointReturnsServiceMetadata() throws Exception {
        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status", is("healthy")))
                .andExpect(jsonPath("$.service", is("report-service")))
                .andExpect(jsonPath("$.version", is("0.1.0")));
    }

    // ---- Helpers ----

    private ReportRequest buildRequest(String name, ReportCategory category,
                                       ReportType type, String requestedBy) {
        ReportRequest request = new ReportRequest(
                name,
                category,
                type,
                requestedBy,
                Instant.now().minusMillis(86400000L * 7),
                Instant.now(),
                null);
        return request;
    }

    private Long createReportAndReturnId(String name, ReportCategory category,
                                         ReportType type, String requestedBy) throws Exception {
        ReportRequest request = buildRequest(name, category, type, requestedBy);
        MvcResult result = mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isAccepted())
                .andReturn();

        String body = result.getResponse().getContentAsString();
        return objectMapper.readTree(body).get("id").asLong();
    }
}
