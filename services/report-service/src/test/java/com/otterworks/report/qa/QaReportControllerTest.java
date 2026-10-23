package com.otterworks.report.qa;

import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import com.otterworks.report.service.ReportGenerationWorker;
import org.junit.After;
import org.junit.Ignore;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.junit4.SpringRunner;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Date;
import java.util.concurrent.TimeUnit;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.everyItem;
import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.is;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * QA audit (docs/qa/analytics-report.md): /api/v1/reports HTTP contract with the
 * async worker mocked so report state can be driven deterministically.
 * {@code @Ignore}d tests document findings RPT-x and should pass once fixed.
 */
@RunWith(SpringRunner.class)
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
public class QaReportControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ReportRepository reportRepository;

    @MockBean
    private ReportGenerationWorker generationWorker;

    @After
    public void cleanup() {
        reportRepository.deleteAll();
    }

    private static String body(String name, String category, String type, String requestedBy, String extra) {
        StringBuilder sb = new StringBuilder("{");
        if (name != null) sb.append("\"reportName\":\"").append(name).append("\",");
        if (category != null) sb.append("\"category\":\"").append(category).append("\",");
        if (type != null) sb.append("\"reportType\":\"").append(type).append("\",");
        if (requestedBy != null) sb.append("\"requestedBy\":\"").append(requestedBy).append("\",");
        if (extra != null) sb.append(extra).append(",");
        sb.setLength(sb.length() - 1);
        return sb.append("}").toString();
    }

    private Report saved(String owner, ReportStatus status, String filePath) {
        Report r = new Report();
        r.setReportName("qa-" + status);
        r.setCategory(ReportCategory.USAGE_ANALYTICS);
        r.setReportType(ReportType.CSV);
        r.setRequestedBy(owner);
        r.setStatus(status);
        r.setCreatedAt(new Date());
        r.setDateFrom(new Date(System.currentTimeMillis() - 86_400_000L));
        r.setDateTo(new Date());
        r.setFilePath(filePath);
        return reportRepository.save(r);
    }

    // ----- create / validation -----

    @Test
    public void createReturns202PendingWithDefaultThirtyDayRangeAndSchedulesWorker() throws Exception {
        MvcResult res = mockMvc.perform(post("/api/v1/reports").contentType(MediaType.APPLICATION_JSON)
                        .content(body("Usage", "USAGE_ANALYTICS", "CSV", "qa-user", null)))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.status", is("PENDING")))
                .andExpect(jsonPath("$.requestedBy", is("qa-user")))
                .andReturn();
        Long id = Long.valueOf(com.jayway.jsonpath.JsonPath.read(res.getResponse().getContentAsString(), "$.id").toString());
        Report r = reportRepository.findById(id).get();
        long spanDays = TimeUnit.MILLISECONDS.toDays(r.getDateTo().getTime() - r.getDateFrom().getTime());
        assertTrue("default range should be ~30 days, was " + spanDays, spanDays >= 29 && spanDays <= 30);
        verify(generationWorker, timeout(2000)).generateReportAsync(id);
    }

    @Test
    public void createKeepsExplicitDateRange() throws Exception {
        mockMvc.perform(post("/api/v1/reports").contentType(MediaType.APPLICATION_JSON)
                        .content(body("Range", "AUDIT_LOG", "PDF", "qa-user",
                                "\"dateFrom\":\"2026-01-01T00:00:00.000+00:00\",\"dateTo\":\"2026-01-31T00:00:00.000+00:00\"")))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.dateFrom", containsString("2026-01-01")))
                .andExpect(jsonPath("$.dateTo", containsString("2026-01-31")));
    }

    @Test
    public void createRejectsMissingReportName() throws Exception {
        mockMvc.perform(post("/api/v1/reports").contentType(MediaType.APPLICATION_JSON)
                        .content(body(null, "USAGE_ANALYTICS", "CSV", "qa-user", null)))
                .andExpect(status().isBadRequest());
    }

    @Test
    public void createRejectsBlankRequestedBy() throws Exception {
        mockMvc.perform(post("/api/v1/reports").contentType(MediaType.APPLICATION_JSON)
                        .content(body("x", "USAGE_ANALYTICS", "CSV", "  ", null)))
                .andExpect(status().isBadRequest());
    }

    @Test
    public void createRejectsMissingCategoryAndType() throws Exception {
        mockMvc.perform(post("/api/v1/reports").contentType(MediaType.APPLICATION_JSON)
                        .content(body("x", null, "CSV", "qa-user", null)))
                .andExpect(status().isBadRequest());
        mockMvc.perform(post("/api/v1/reports").contentType(MediaType.APPLICATION_JSON)
                        .content(body("x", "USAGE_ANALYTICS", null, "qa-user", null)))
                .andExpect(status().isBadRequest());
    }

    @Test
    public void createRejectsUnknownEnumValues() throws Exception {
        mockMvc.perform(post("/api/v1/reports").contentType(MediaType.APPLICATION_JSON)
                        .content(body("x", "NOT_A_CATEGORY", "CSV", "qa-user", null)))
                .andExpect(status().isBadRequest());
        mockMvc.perform(post("/api/v1/reports").contentType(MediaType.APPLICATION_JSON)
                        .content(body("x", "USAGE_ANALYTICS", "DOCX", "qa-user", null)))
                .andExpect(status().isBadRequest());
    }

    @Test
    public void createRejectsMalformedJson() throws Exception {
        mockMvc.perform(post("/api/v1/reports").contentType(MediaType.APPLICATION_JSON).content("{nope"))
                .andExpect(status().isBadRequest());
    }

    @Ignore("Finding RPT-2: ReportRequest/ReportService accept dateFrom > dateTo (no range validation)")
    @Test
    public void createRejectsInvertedDateRange() throws Exception {
        mockMvc.perform(post("/api/v1/reports").contentType(MediaType.APPLICATION_JSON)
                        .content(body("Inverted", "USAGE_ANALYTICS", "CSV", "qa-user",
                                "\"dateFrom\":\"2026-02-01T00:00:00.000+00:00\",\"dateTo\":\"2026-01-01T00:00:00.000+00:00\"")))
                .andExpect(status().isBadRequest());
    }

    @Ignore("Finding RPT-3: SecurityConfig permits /api/v1/reports/** without authentication (TODO: Add JWT validation)")
    @Test
    public void unauthenticatedRequestsAreRejected() throws Exception {
        mockMvc.perform(get("/api/v1/reports")).andExpect(status().isUnauthorized());
    }

    // ----- read / list -----

    @Test
    public void getUnknownReportReturns404() throws Exception {
        mockMvc.perform(get("/api/v1/reports/987654")).andExpect(status().isNotFound());
    }

    @Test
    public void getNonNumericIdReturns400() throws Exception {
        mockMvc.perform(get("/api/v1/reports/abc")).andExpect(status().isBadRequest());
    }

    @Test
    public void listByUserReturnsOnlyThatUsersReports() throws Exception {
        saved("alice", ReportStatus.COMPLETED, null);
        saved("alice", ReportStatus.PENDING, null);
        saved("bob", ReportStatus.COMPLETED, null);
        mockMvc.perform(get("/api/v1/reports").param("userId", "alice"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total", is(2)))
                .andExpect(jsonPath("$.reports[*].requestedBy", everyItem(is("alice"))));
    }

    @Test
    public void listWithoutFiltersReturnsOnlyCompletedReports() throws Exception {
        saved("alice", ReportStatus.COMPLETED, null);
        saved("alice", ReportStatus.FAILED, null);
        mockMvc.perform(get("/api/v1/reports"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports", hasSize(1)))
                .andExpect(jsonPath("$.reports[0].status", is("COMPLETED")));
    }

    @Test
    public void listByStatusFiltersAndRejectsUnknownStatus() throws Exception {
        saved("alice", ReportStatus.FAILED, null);
        saved("bob", ReportStatus.COMPLETED, null);
        mockMvc.perform(get("/api/v1/reports").param("status", "FAILED"))
                .andExpect(jsonPath("$.total", is(1)))
                .andExpect(jsonPath("$.reports[0].status", is("FAILED")));
        mockMvc.perform(get("/api/v1/reports").param("status", "BOGUS"))
                .andExpect(status().isBadRequest());
    }

    // ----- download lifecycle -----

    @Test
    public void downloadUnknownReportReturns404() throws Exception {
        mockMvc.perform(get("/api/v1/reports/424242/download")).andExpect(status().isNotFound());
    }

    @Test
    public void downloadPendingOrGeneratingReturns409() throws Exception {
        Report pending = saved("alice", ReportStatus.PENDING, null);
        Report generating = saved("alice", ReportStatus.GENERATING, null);
        mockMvc.perform(get("/api/v1/reports/" + pending.getId() + "/download")).andExpect(status().isConflict());
        mockMvc.perform(get("/api/v1/reports/" + generating.getId() + "/download")).andExpect(status().isConflict());
    }

    @Test
    public void downloadFailedOrFilelessReportReturns404() throws Exception {
        Report failed = saved("alice", ReportStatus.FAILED, "/tmp/whatever.csv");
        Report noFile = saved("alice", ReportStatus.COMPLETED, null);
        Report missing = saved("alice", ReportStatus.COMPLETED, "/tmp/qa-does-not-exist-" + System.nanoTime() + ".csv");
        mockMvc.perform(get("/api/v1/reports/" + failed.getId() + "/download")).andExpect(status().isNotFound());
        mockMvc.perform(get("/api/v1/reports/" + noFile.getId() + "/download")).andExpect(status().isNotFound());
        mockMvc.perform(get("/api/v1/reports/" + missing.getId() + "/download")).andExpect(status().isNotFound());
    }

    @Test
    public void downloadCompletedReportStreamsFileAsAttachment() throws Exception {
        File f = File.createTempFile("qa-report", ".csv");
        f.deleteOnExit();
        Files.write(f.toPath(), "a,b\n1,2\n".getBytes(StandardCharsets.UTF_8));
        Report done = saved("alice", ReportStatus.COMPLETED, f.getAbsolutePath());
        mockMvc.perform(get("/api/v1/reports/" + done.getId() + "/download"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Disposition", containsString("attachment; filename=\"" + f.getName())))
                .andExpect(header().string("Content-Type", containsString("text/csv")))
                .andExpect(content().string("a,b\n1,2\n"));
    }

    // ----- delete -----

    @Test
    public void deleteRemovesRecordAndFile() throws Exception {
        File f = File.createTempFile("qa-delete", ".csv");
        Report done = saved("alice", ReportStatus.COMPLETED, f.getAbsolutePath());
        mockMvc.perform(delete("/api/v1/reports/" + done.getId())).andExpect(status().isNoContent());
        mockMvc.perform(get("/api/v1/reports/" + done.getId())).andExpect(status().isNotFound());
        assertFalse("report file should be deleted after commit", f.exists());
    }

    @Test
    public void deleteUnknownReportReturns404() throws Exception {
        mockMvc.perform(delete("/api/v1/reports/13579")).andExpect(status().isNotFound());
    }
}
