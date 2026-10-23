package com.otterworks.report.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.report.model.Report;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportStatus;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import com.otterworks.report.security.TestTokens;
import org.junit.Test;
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

import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.is;
import static org.junit.Assert.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Authentication and per-owner scoping of /api/v1/reports.
 */
@RunWith(SpringRunner.class)
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
public class ReportAuthorizationIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private ReportRepository reportRepository;

    @Test
    public void everyReportEndpointRejectsAnonymousCallers() throws Exception {
        Long id = completedReport("anon-victim").getId();

        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request("anon-victim"))))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports").param("userId", "anon-victim")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports/" + id)).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports/" + id + "/download")).andExpect(status().isUnauthorized());
        mockMvc.perform(delete("/api/v1/reports/" + id)).andExpect(status().isUnauthorized());

        assertTrue(reportRepository.findById(id).isPresent());
    }

    @Test
    public void forgedGatewayHeaderAndBadTokensAreRejected() throws Exception {
        Long id = completedReport("header-victim").getId();

        mockMvc.perform(get("/api/v1/reports/" + id).header("X-User-ID", "header-victim"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports/" + id)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.sign("HS256",
                                "attacker-chosen-secret-0123456789abcdef",
                                TestTokens.claims("header-victim", "access", System.currentTimeMillis() / 1000L + 600))))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error", is("missing or invalid bearer token")));
        mockMvc.perform(get("/api/v1/reports/" + id)
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.sign("HS256", TestTokens.SECRET,
                                TestTokens.claims("header-victim", "refresh", System.currentTimeMillis() / 1000L + 600))))
                .andExpect(status().isUnauthorized());
    }

    @Test
    public void createdReportIsOwnedByTheCallerNotTheBodyRequestedBy() throws Exception {
        mockMvc.perform(post("/api/v1/reports")
                        .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("real-caller"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request("someone-else"))))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.requestedBy", is("real-caller")));
    }

    @Test
    public void createWithoutRequestedByIsAccepted() throws Exception {
        mockMvc.perform(post("/api/v1/reports")
                        .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("no-body-owner"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request(null))))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.requestedBy", is("no-body-owner")));
    }

    @Test
    public void ownerCanReadDownloadAndDeleteTheirReport() throws Exception {
        Report report = completedReport("owner-1");
        String owner = TestTokens.bearer("owner-1");

        mockMvc.perform(get("/api/v1/reports/" + report.getId()).header(HttpHeaders.AUTHORIZATION, owner))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.requestedBy", is("owner-1")));
        mockMvc.perform(get("/api/v1/reports/" + report.getId() + "/download").header(HttpHeaders.AUTHORIZATION, owner))
                .andExpect(status().isOk())
                .andExpect(content().string("secret,report\n"));
        mockMvc.perform(delete("/api/v1/reports/" + report.getId()).header(HttpHeaders.AUTHORIZATION, owner))
                .andExpect(status().isNoContent());
    }

    @Test
    public void otherUsersGet404ForReadDownloadAndDelete() throws Exception {
        Report report = completedReport("owner-2");
        String intruder = TestTokens.bearer("intruder-2");

        mockMvc.perform(get("/api/v1/reports/" + report.getId()).header(HttpHeaders.AUTHORIZATION, intruder))
                .andExpect(status().isNotFound());
        mockMvc.perform(get("/api/v1/reports/" + report.getId() + "/download").header(HttpHeaders.AUTHORIZATION, intruder))
                .andExpect(status().isNotFound());
        mockMvc.perform(delete("/api/v1/reports/" + report.getId()).header(HttpHeaders.AUTHORIZATION, intruder))
                .andExpect(status().isNotFound());

        assertTrue(reportRepository.findById(report.getId()).isPresent());
        assertTrue(new File(report.getFilePath()).exists());
    }

    @Test
    public void listIsScopedToTheCaller() throws Exception {
        completedReport("lister-a");
        completedReport("lister-b");

        mockMvc.perform(get("/api/v1/reports").header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("lister-a")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports", hasSize(1)))
                .andExpect(jsonPath("$.reports[0].requestedBy", is("lister-a")));
        mockMvc.perform(get("/api/v1/reports").param("status", "COMPLETED")
                        .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("lister-a")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports", hasSize(1)));
        mockMvc.perform(get("/api/v1/reports").param("userId", "lister-a")
                        .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("lister-a")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports", hasSize(1)));
        mockMvc.perform(get("/api/v1/reports").param("userId", "lister-a")
                        .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("lister-b")))
                .andExpect(status().isForbidden());
    }

    @Test
    public void adminCanAccessAnyReport() throws Exception {
        Report report = completedReport("owner-3");
        String admin = TestTokens.bearer("admin-3", "USER", "ADMIN");

        mockMvc.perform(get("/api/v1/reports").param("userId", "owner-3").header(HttpHeaders.AUTHORIZATION, admin))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports", hasSize(1)));
        mockMvc.perform(get("/api/v1/reports/" + report.getId() + "/download").header(HttpHeaders.AUTHORIZATION, admin))
                .andExpect(status().isOk());
        mockMvc.perform(delete("/api/v1/reports/" + report.getId()).header(HttpHeaders.AUTHORIZATION, admin))
                .andExpect(status().isNoContent());
    }

    private ReportRequest request(String requestedBy) {
        ReportRequest request = new ReportRequest();
        request.setReportName("Authz Report");
        request.setCategory(ReportCategory.AUDIT_LOG);
        request.setReportType(ReportType.CSV);
        request.setRequestedBy(requestedBy);
        return request;
    }

    private Report completedReport(String owner) throws Exception {
        File file = File.createTempFile("authz-report-", ".csv");
        file.deleteOnExit();
        Files.write(file.toPath(), "secret,report\n".getBytes(StandardCharsets.UTF_8));

        Report report = new Report();
        report.setReportName("Completed " + owner);
        report.setCategory(ReportCategory.AUDIT_LOG);
        report.setReportType(ReportType.CSV);
        report.setRequestedBy(owner);
        report.setStatus(ReportStatus.COMPLETED);
        report.setCreatedAt(new Date());
        report.setFilePath(file.getAbsolutePath());
        return reportRepository.save(report);
    }
}
