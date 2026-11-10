package com.otterworks.report.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.report.TestTokens;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportType;
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
import org.springframework.test.web.servlet.MvcResult;

import java.util.UUID;

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
 * Report endpoints authenticate the caller from the access token, scope every report to
 * its owner, and reserve audit/compliance/user-activity reports for administrators.
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

    private final String alice = "alice-" + UUID.randomUUID();
    private final String mallory = "mallory-" + UUID.randomUUID();

    @Test
    public void requestsWithoutAValidAccessTokenAreRejected() throws Exception {
        String body = objectMapper.writeValueAsString(request(ReportCategory.USAGE_ANALYTICS, alice));

        mockMvc.perform(post("/api/v1/reports").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports/1").header(HttpHeaders.AUTHORIZATION, TestTokens.wrongSecret(alice, "ADMIN")))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports").header(HttpHeaders.AUTHORIZATION, TestTokens.expired(alice)))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports").header(HttpHeaders.AUTHORIZATION, TestTokens.refresh(alice)))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports").header("X-User-ID", alice))
                .andExpect(status().isUnauthorized());
    }

    @Test
    public void requesterComesFromTheTokenNotTheBody() throws Exception {
        String body = objectMapper.writeValueAsString(request(ReportCategory.USAGE_ANALYTICS, alice));

        MvcResult result = mockMvc.perform(post("/api/v1/reports")
                        .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer(mallory))
                        .contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.requestedBy", is(mallory)))
                .andReturn();
        long id = idOf(result);

        mockMvc.perform(get("/api/v1/reports").header(HttpHeaders.AUTHORIZATION, TestTokens.bearer(alice)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total", is(0)));
        mockMvc.perform(get("/api/v1/reports/" + id).header(HttpHeaders.AUTHORIZATION, TestTokens.bearer(alice)))
                .andExpect(status().isNotFound());
    }

    @Test
    public void anotherUserCannotReadDownloadListOrDeleteAReport() throws Exception {
        long id = create(alice, ReportCategory.USAGE_ANALYTICS);
        String asMallory = TestTokens.bearer(mallory);

        mockMvc.perform(get("/api/v1/reports/" + id).header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isNotFound());
        mockMvc.perform(get("/api/v1/reports/" + id + "/download").header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isNotFound());
        mockMvc.perform(delete("/api/v1/reports/" + id).header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isNotFound());
        mockMvc.perform(get("/api/v1/reports").param("userId", alice).header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isForbidden());
        mockMvc.perform(get("/api/v1/reports").header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total", is(0)));
        mockMvc.perform(get("/api/v1/reports").param("status", "COMPLETED").header(HttpHeaders.AUTHORIZATION, asMallory))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports[*].requestedBy", everyItem(is(mallory))));

        // An admin of another account gets no cross-user access either.
        mockMvc.perform(get("/api/v1/reports/" + id).header(HttpHeaders.AUTHORIZATION, TestTokens.bearer(mallory, "ADMIN")))
                .andExpect(status().isNotFound());

        String asAlice = TestTokens.bearer(alice);
        mockMvc.perform(get("/api/v1/reports/" + id).header(HttpHeaders.AUTHORIZATION, asAlice))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.requestedBy", is(alice)));
        mockMvc.perform(get("/api/v1/reports").header(HttpHeaders.AUTHORIZATION, asAlice))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.reports[*].id", hasItem((int) id)));
        mockMvc.perform(delete("/api/v1/reports/" + id).header(HttpHeaders.AUTHORIZATION, asAlice))
                .andExpect(status().isNoContent());
    }

    @Test
    public void sensitiveCategoriesRequireAnAdministrator() throws Exception {
        for (ReportCategory category : new ReportCategory[]{
                ReportCategory.AUDIT_LOG, ReportCategory.COMPLIANCE, ReportCategory.USER_ACTIVITY}) {
            String body = objectMapper.writeValueAsString(request(category, mallory));

            mockMvc.perform(post("/api/v1/reports")
                            .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer(mallory, "USER", "EDITOR"))
                            .contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isForbidden());

            mockMvc.perform(post("/api/v1/reports")
                            .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer(alice, "USER", "ADMIN"))
                            .contentType(MediaType.APPLICATION_JSON).content(body))
                    .andExpect(status().isAccepted())
                    .andExpect(jsonPath("$.category", is(category.name())));
        }

        mockMvc.perform(get("/api/v1/reports").header(HttpHeaders.AUTHORIZATION, TestTokens.bearer(mallory)))
                .andExpect(jsonPath("$.reports[*].category", not(hasItem("AUDIT_LOG"))));
    }

    @Test
    public void ownerWhoLostAdminCannotReadASensitiveReport() throws Exception {
        long id = create(alice, ReportCategory.AUDIT_LOG, "ADMIN");

        mockMvc.perform(get("/api/v1/reports/" + id).header(HttpHeaders.AUTHORIZATION, TestTokens.bearer(alice)))
                .andExpect(status().isForbidden());
        mockMvc.perform(get("/api/v1/reports/" + id + "/download").header(HttpHeaders.AUTHORIZATION, TestTokens.bearer(alice)))
                .andExpect(status().isForbidden());
        mockMvc.perform(get("/api/v1/reports/" + id).header(HttpHeaders.AUTHORIZATION, TestTokens.bearer(alice, "OWNER")))
                .andExpect(status().isOk());
    }

    private long create(String userId, ReportCategory category, String... roles) throws Exception {
        MvcResult result = mockMvc.perform(post("/api/v1/reports")
                        .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer(userId, roles))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request(category, userId))))
                .andExpect(status().isAccepted())
                .andReturn();
        return idOf(result);
    }

    private long idOf(MvcResult result) throws Exception {
        return objectMapper.readTree(result.getResponse().getContentAsString()).get("id").asLong();
    }

    private static ReportRequest request(ReportCategory category, String requestedBy) {
        ReportRequest request = new ReportRequest();
        request.setReportName("Authorization test " + category);
        request.setCategory(category);
        request.setReportType(ReportType.CSV);
        request.setRequestedBy(requestedBy);
        return request;
    }
}
