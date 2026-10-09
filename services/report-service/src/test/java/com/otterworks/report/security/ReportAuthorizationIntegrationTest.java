package com.otterworks.report.security;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.repository.ReportRepository;
import com.otterworks.report.service.ReportService;
import com.otterworks.report.support.TestTokens;
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
import org.springframework.test.web.servlet.request.RequestPostProcessor;

import java.util.Date;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

import static com.otterworks.report.support.TestTokens.admin;
import static com.otterworks.report.support.TestTokens.bearer;
import static com.otterworks.report.support.TestTokens.user;
import static org.hamcrest.Matchers.everyItem;
import static org.hamcrest.Matchers.hasItem;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.not;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Authentication and ownership rules of the report API.
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

    // ---- Authentication ----

    @Test
    public void requestsWithoutTokenAreRejected() throws Exception {
        mockMvc.perform(get("/api/v1/reports")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports/1")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports/1/download")).andExpect(status().isUnauthorized());
        mockMvc.perform(delete("/api/v1/reports/1")).andExpect(status().isUnauthorized());
        mockMvc.perform(post("/api/v1/reports")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(
                                request(ReportCategory.USAGE_ANALYTICS, null))))
                .andExpect(status().isUnauthorized());
    }

    @Test
    public void tokenSignedWithAnotherSecretIsRejected() throws Exception {
        String forged = TestTokens.signedToken("some-other-secret-that-is-long-enough-for-hs256",
                "attacker", "access", "ADMIN");
        mockMvc.perform(get("/api/v1/reports").with(bearer(forged)))
                .andExpect(status().isUnauthorized());
    }

    @Test
    public void refreshTokenIsRejected() throws Exception {
        String refresh = TestTokens.signedToken(TestTokens.SECRET, "user-a", "refresh");
        mockMvc.perform(get("/api/v1/reports").with(bearer(refresh)))
                .andExpect(status().isUnauthorized());
    }

    @Test
    public void spoofedUserHeaderWithoutTokenIsRejected() throws Exception {
        mockMvc.perform(get("/api/v1/reports").header("X-User-ID", "user-a"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    public void malformedAuthorizationHeaderIsRejected() throws Exception {
        mockMvc.perform(get("/api/v1/reports").header(HttpHeaders.AUTHORIZATION, "Bearer not-a-jwt"))
                .andExpect(status().isUnauthorized());
    }

    // ---- Create ----

    @Test
    public void requesterIsTakenFromTokenWhenOmitted() throws Exception {
        String alice = uniqueUser("alice");
        mockMvc.perform(post("/api/v1/reports")
                        .with(user(alice))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(
                                request(ReportCategory.USAGE_ANALYTICS, null))))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.requestedBy", is(alice)));
    }

    @Test
    public void cannotCreateReportForAnotherUser() throws Exception {
        mockMvc.perform(post("/api/v1/reports")
                        .with(user(uniqueUser("mallory")))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(
                                request(ReportCategory.USAGE_ANALYTICS, "victim"))))
                .andExpect(status().isForbidden());
    }

    @Test
    public void tenantWideCategoriesRequireAdmin() throws Exception {
        String bob = uniqueUser("bob");
        for (ReportCategory category : ReportCategory.values()) {
            if (!category.isAdminOnly()) {
                continue;
            }
            mockMvc.perform(post("/api/v1/reports")
                            .with(user(bob))
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(objectMapper.writeValueAsString(request(category, bob))))
                    .andExpect(status().isForbidden());
        }

        String admin = uniqueUser("admin");
        mockMvc.perform(post("/api/v1/reports")
                        .with(admin(admin))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request(ReportCategory.AUDIT_LOG, admin))))
                .andExpect(status().isAccepted());
    }

    @Test
    public void adminOnlyCategoriesCoverAuditAndUserActivityFeeds() {
        org.junit.Assert.assertTrue(ReportCategory.AUDIT_LOG.isAdminOnly());
        org.junit.Assert.assertTrue(ReportCategory.COMPLIANCE.isAdminOnly());
        org.junit.Assert.assertTrue(ReportCategory.USER_ACTIVITY.isAdminOnly());
        org.junit.Assert.assertTrue(ReportCategory.STORAGE_SUMMARY.isAdminOnly());
        org.junit.Assert.assertFalse(ReportCategory.USAGE_ANALYTICS.isAdminOnly());
    }

    @Test
    public void nonAdminReportsAreScopedToRequesterRows() throws Exception {
        String alice = uniqueUser("alice");
        ReportRequest request = request(ReportCategory.USAGE_ANALYTICS, null);
        Map<String, String> params = new HashMap<>();
        params.put(ReportService.OWNER_SCOPE_PARAM, "victim");
        params.put("source", "authz-test");
        request.setParameters(params);

        String body = mockMvc.perform(post("/api/v1/reports")
                        .with(user(alice))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isAccepted())
                .andReturn().getResponse().getContentAsString();
        long id = objectMapper.readTree(body).get("id").asLong();

        Map<?, ?> stored = objectMapper.readValue(reportRepository.findById(id).get().getParameters(), Map.class);
        org.junit.Assert.assertEquals(alice, stored.get(ReportService.OWNER_SCOPE_PARAM));
        org.junit.Assert.assertEquals("authz-test", stored.get("source"));
    }

    @Test
    public void adminReportsAreNotScoped() throws Exception {
        String admin = uniqueUser("admin");
        ReportRequest request = request(ReportCategory.USAGE_ANALYTICS, null);
        Map<String, String> params = new HashMap<>();
        params.put(ReportService.OWNER_SCOPE_PARAM, "someone");
        request.setParameters(params);

        String body = mockMvc.perform(post("/api/v1/reports")
                        .with(admin(admin))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isAccepted())
                .andReturn().getResponse().getContentAsString();
        long id = objectMapper.readTree(body).get("id").asLong();

        org.junit.Assert.assertNull(reportRepository.findById(id).get().getParameters());
    }

    // ---- Read / download / delete ----

    @Test
    public void otherUsersReportsAreInvisible() throws Exception {
        String alice = uniqueUser("alice");
        String mallory = uniqueUser("mallory");
        long id = createReport(alice);

        mockMvc.perform(get("/api/v1/reports/" + id).with(user(mallory)))
                .andExpect(status().isNotFound());
        mockMvc.perform(get("/api/v1/reports/" + id + "/download").with(user(mallory)))
                .andExpect(status().isNotFound());
        mockMvc.perform(delete("/api/v1/reports/" + id).with(user(mallory)))
                .andExpect(status().isNotFound());

        // still there for its owner
        mockMvc.perform(get("/api/v1/reports/" + id).with(user(alice)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.requestedBy", is(alice)));
    }

    @Test
    public void ownerAndAdminCanAccessReport() throws Exception {
        String alice = uniqueUser("alice");
        long id = createReport(alice);

        mockMvc.perform(get("/api/v1/reports/" + id).with(admin(uniqueUser("admin"))))
                .andExpect(status().isOk());
        mockMvc.perform(delete("/api/v1/reports/" + id).with(user(alice)))
                .andExpect(status().isNoContent());
    }

    // ---- List ----

    @Test
    public void listWithoutUserIdOnlyReturnsCallersReports() throws Exception {
        String alice = uniqueUser("alice");
        String mallory = uniqueUser("mallory");
        createReport(alice);
        long malloryReport = createReport(mallory);

        mockMvc.perform(get("/api/v1/reports").with(user(mallory)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports[*].requestedBy", everyItem(is(mallory))))
                .andExpect(jsonPath("$.reports[*].id", hasItem((int) malloryReport)));

        mockMvc.perform(get("/api/v1/reports").param("status", "COMPLETED").with(user(mallory)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports[*].requestedBy", everyItem(is(mallory))));
    }

    @Test
    public void cannotListAnotherUsersReports() throws Exception {
        String alice = uniqueUser("alice");
        createReport(alice);

        mockMvc.perform(get("/api/v1/reports").param("userId", alice).with(user(uniqueUser("mallory"))))
                .andExpect(status().isForbidden());
    }

    @Test
    public void adminCanListAnyUsersReports() throws Exception {
        String alice = uniqueUser("alice");
        long id = createReport(alice);

        mockMvc.perform(get("/api/v1/reports").param("userId", alice).with(admin(uniqueUser("admin"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports[*].id", hasItem((int) id)))
                .andExpect(jsonPath("$.reports[*].requestedBy", not(hasItem("nobody"))));
    }

    // ---- Helpers ----

    private static String uniqueUser(String prefix) {
        return prefix + "-" + UUID.randomUUID();
    }

    private static ReportRequest request(ReportCategory category, String requestedBy) {
        ReportRequest request = new ReportRequest();
        request.setReportName("Authz " + category);
        request.setCategory(category);
        request.setReportType(ReportType.CSV);
        request.setRequestedBy(requestedBy);
        request.setDateFrom(new Date(System.currentTimeMillis() - 86400000L));
        request.setDateTo(new Date());
        return request;
    }

    private long createReport(String owner) throws Exception {
        RequestPostProcessor auth = user(owner);
        String body = mockMvc.perform(post("/api/v1/reports")
                        .with(auth)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request(ReportCategory.USAGE_ANALYTICS, owner))))
                .andExpect(status().isAccepted())
                .andReturn().getResponse().getContentAsString();
        JsonNode node = objectMapper.readTree(body);
        return node.get("id").asLong();
    }
}
