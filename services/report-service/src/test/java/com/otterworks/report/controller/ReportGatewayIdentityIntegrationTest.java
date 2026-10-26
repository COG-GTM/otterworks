package com.otterworks.report.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.otterworks.report.model.ReportCategory;
import com.otterworks.report.model.ReportRequest;
import com.otterworks.report.model.ReportType;
import com.otterworks.report.security.TestJwt;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.junit4.SpringRunner;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Without a JWT secret the service trusts the identity headers api-gateway derives from the
 * JWT it validated; ownership and admin checks must hold the same way.
 */
@RunWith(SpringRunner.class)
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@TestPropertySource(properties = "otterworks.security.jwt-secret=")
public class ReportGatewayIdentityIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    private final String alice = "gw-alice-" + System.nanoTime();
    private final String mallory = "gw-mallory-" + System.nanoTime();

    @Test
    public void requestsWithoutGatewayIdentityAreRejected() throws Exception {
        mockMvc.perform(get("/api/v1/reports")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports").header("X-User-ID", "  ")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports")
                        .header(HttpHeaders.AUTHORIZATION, TestJwt.bearer(alice)))
                .andExpect(status().isUnauthorized());
    }

    @Test
    public void ownershipIsEnforcedForGatewayCallers() throws Exception {
        String body = mockMvc.perform(post("/api/v1/reports")
                        .header("X-User-ID", alice)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request(ReportCategory.USAGE_ANALYTICS, mallory))))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.requestedBy").value(alice))
                .andReturn().getResponse().getContentAsString();
        long id = objectMapper.readTree(body).get("id").asLong();

        mockMvc.perform(get("/api/v1/reports/" + id).header("X-User-ID", mallory))
                .andExpect(status().isNotFound());
        mockMvc.perform(get("/api/v1/reports/" + id + "/download").header("X-User-ID", mallory))
                .andExpect(status().isNotFound());
        mockMvc.perform(delete("/api/v1/reports/" + id).header("X-User-ID", mallory))
                .andExpect(status().isNotFound());
        mockMvc.perform(get("/api/v1/reports").param("userId", alice).header("X-User-ID", mallory))
                .andExpect(status().isForbidden());

        mockMvc.perform(get("/api/v1/reports/" + id).header("X-User-ID", alice))
                .andExpect(status().isOk());
        mockMvc.perform(delete("/api/v1/reports/" + id).header("X-User-ID", alice))
                .andExpect(status().isNoContent());
    }

    @Test
    public void adminCategoriesNeedTheGatewayAdminRole() throws Exception {
        mockMvc.perform(post("/api/v1/reports")
                        .header("X-User-ID", mallory)
                        .header("X-User-Roles", "USER")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request(ReportCategory.AUDIT_LOG, mallory))))
                .andExpect(status().isForbidden());
        mockMvc.perform(post("/api/v1/reports")
                        .header("X-User-ID", alice)
                        .header("X-User-Roles", "USER, ADMIN")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request(ReportCategory.AUDIT_LOG, alice))))
                .andExpect(status().isAccepted());
    }

    private static ReportRequest request(ReportCategory category, String requestedBy) {
        ReportRequest request = new ReportRequest();
        request.setReportName("Gateway identity report");
        request.setCategory(category);
        request.setReportType(ReportType.CSV);
        request.setRequestedBy(requestedBy);
        return request;
    }
}
