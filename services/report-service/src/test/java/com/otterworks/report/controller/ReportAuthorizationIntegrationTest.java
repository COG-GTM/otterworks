package com.otterworks.report.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import com.otterworks.report.security.TestJwt;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.junit4.SpringRunner;
import org.springframework.test.web.servlet.MockMvc;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Date;

import static org.hamcrest.Matchers.everyItem;
import static org.hamcrest.Matchers.hasItem;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.not;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Caller identity and ownership checks on /api/v1/reports.
 */
@RunWith(SpringRunner.class)
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
public class ReportAuthorizationIntegrationTest {

    @Rule
    public TemporaryFolder tmp = new TemporaryFolder();

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private ReportRepository reportRepository;

    private final String alice = "authz-alice-" + System.nanoTime();
    private final String mallory = "authz-mallory-" + System.nanoTime();

    // ---- authentication ----

    @Test
    public void requestsWithoutTokenAreRejected() throws Exception {
        mockMvc.perform(get("/api/v1/reports")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports/1")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports/1/download")).andExpect(status().isUnauthorized());
        mockMvc.perform(delete("/api/v1/reports/1")).andExpect(status().isUnauthorized());
        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request(ReportCategory.USAGE_ANALYTICS, alice))))
                .andExpect(status().isUnauthorized());
    }

    @Test
    public void forgedOrSpoofedIdentityIsRejected() throws Exception {
        java.util.Map<String, Object> claims = new java.util.HashMap<>();
        claims.put("sub", alice);
        claims.put("exp", System.currentTimeMillis() / 1000L + 600);
        String forged = TestJwt.sign("HS256", claims, "attacker-chosen-secret");

        mockMvc.perform(get("/api/v1/reports").header(HttpHeaders.AUTHORIZATION, "Bearer " + forged))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports").header("X-User-ID", alice))
                .andExpect(status().isUnauthorized());
    }

    @Test
    public void healthStaysPublic() throws Exception {
        mockMvc.perform(get("/health")).andExpect(status().isOk());
    }

    // ---- create ----

    @Test
    public void ownerComesFromTokenNotRequestBody() throws Exception {
        mockMvc.perform(post("/api/v1/reports")
                        .header(HttpHeaders.AUTHORIZATION, TestJwt.bearer(mallory))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request(ReportCategory.USAGE_ANALYTICS, alice))))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.requestedBy", is(mallory)));
    }

    @Test
    public void requestedByIsOptional() throws Exception {
        mockMvc.perform(post("/api/v1/reports")
                        .header(HttpHeaders.AUTHORIZATION, TestJwt.bearer(alice))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request(ReportCategory.SYSTEM_HEALTH, null))))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.requestedBy", is(alice)));
    }

    @Test
    public void nonAdminCannotCreatePlatformWideCategories() throws Exception {
        long before = reportRepository.count();
        for (ReportCategory category : ReportCategory.values()) {
            if (!category.requiresAdmin()) {
                continue;
            }
            mockMvc.perform(post("/api/v1/reports")
                            .header(HttpHeaders.AUTHORIZATION, TestJwt.bearer(mallory))
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(objectMapper.writeValueAsString(request(category, alice))))
                    .andExpect(status().isForbidden());
        }
        assertEquals(before, reportRepository.count());
    }

    @Test
    public void adminCanCreateAuditLogReport() throws Exception {
        mockMvc.perform(post("/api/v1/reports")
                        .header(HttpHeaders.AUTHORIZATION, TestJwt.adminBearer(alice))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request(ReportCategory.AUDIT_LOG, null))))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.category", is("AUDIT_LOG")))
                .andExpect(jsonPath("$.requestedBy", is(alice)));
    }

    // ---- read / download / delete ----

    @Test
    public void otherUserCannotReadDownloadOrDeleteReport() throws Exception {
        Report report = completedReport(alice, "alice-secret-contents");
        String asMallory = TestJwt.bearer(mallory);

        mockMvc.perform(get("/api/v1/reports/" + report.getId()).header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isNotFound());
        mockMvc.perform(get("/api/v1/reports/" + report.getId() + "/download").header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isNotFound());
        mockMvc.perform(delete("/api/v1/reports/" + report.getId()).header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isNotFound());

        assertTrue(reportRepository.findById(report.getId()).isPresent());
        assertTrue(new File(report.getFilePath()).exists());
    }

    @Test
    public void ownerCanReadDownloadAndDeleteReport() throws Exception {
        Report report = completedReport(alice, "alice-secret-contents");
        String asAlice = TestJwt.bearer(alice);

        mockMvc.perform(get("/api/v1/reports/" + report.getId()).header(HttpHeaders.AUTHORIZATION, asAlice))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.requestedBy", is(alice)));
        mockMvc.perform(get("/api/v1/reports/" + report.getId() + "/download").header(HttpHeaders.AUTHORIZATION, asAlice))
                .andExpect(status().isOk())
                .andExpect(content().string("alice-secret-contents"));
        mockMvc.perform(delete("/api/v1/reports/" + report.getId()).header(HttpHeaders.AUTHORIZATION, asAlice))
                .andExpect(status().isNoContent());
        assertTrue(!reportRepository.findById(report.getId()).isPresent());
    }

    @Test
    public void adminCanReadAndDeleteAnyReport() throws Exception {
        Report report = completedReport(alice, "alice-secret-contents");
        String asAdmin = TestJwt.adminBearer("authz-admin");

        mockMvc.perform(get("/api/v1/reports/" + report.getId() + "/download").header(HttpHeaders.AUTHORIZATION, asAdmin))
                .andExpect(status().isOk());
        mockMvc.perform(delete("/api/v1/reports/" + report.getId()).header(HttpHeaders.AUTHORIZATION, asAdmin))
                .andExpect(status().isNoContent());
    }

    // ---- list ----

    @Test
    public void nonAdminListsOnlyOwnReports() throws Exception {
        Report aliceReport = completedReport(alice, "a");
        Report malloryReport = completedReport(mallory, "m");
        String asMallory = TestJwt.bearer(mallory);

        mockMvc.perform(get("/api/v1/reports").param("userId", alice).header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isForbidden());

        mockMvc.perform(get("/api/v1/reports").header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports[*].requestedBy", everyItem(is(mallory))))
                .andExpect(jsonPath("$.reports[*].id", hasItem(malloryReport.getId().intValue())));

        mockMvc.perform(get("/api/v1/reports").param("status", "COMPLETED").header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports[*].requestedBy", everyItem(is(mallory))))
                .andExpect(jsonPath("$.reports[*].id", not(hasItem(aliceReport.getId().intValue()))));

        mockMvc.perform(get("/api/v1/reports").param("userId", mallory).header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total", is(1)));
    }

    @Test
    public void adminCanListAnotherUsersReports() throws Exception {
        Report aliceReport = completedReport(alice, "a");
        mockMvc.perform(get("/api/v1/reports").param("userId", alice)
                        .header(HttpHeaders.AUTHORIZATION, TestJwt.adminBearer("authz-admin")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports[*].id", hasItem(aliceReport.getId().intValue())));
    }

    // ---- helpers ----

    private ReportRequest request(ReportCategory category, String requestedBy) {
        ReportRequest request = new ReportRequest();
        request.setReportName("Authz " + category);
        request.setCategory(category);
        request.setReportType(ReportType.CSV);
        request.setRequestedBy(requestedBy);
        request.setDateFrom(new Date(System.currentTimeMillis() - 86400000L));
        request.setDateTo(new Date());
        return request;
    }

    private Report completedReport(String owner, String contents) throws Exception {
        File file = tmp.newFile();
        Files.write(file.toPath(), contents.getBytes(StandardCharsets.UTF_8));
        Report report = new Report();
        report.setReportName("Seeded report");
        report.setCategory(ReportCategory.USAGE_ANALYTICS);
        report.setReportType(ReportType.CSV);
        report.setRequestedBy(owner);
        report.setStatus(ReportStatus.COMPLETED);
        report.setCreatedAt(new Date());
        report.setCompletedAt(new Date());
        report.setFilePath(file.getAbsolutePath());
        report.setFileSizeBytes(file.length());
        return reportRepository.save(report);
    }
}
