package com.otterworks.report.controller;

import com.otterworks.report.security.TestJwt;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.junit4.SpringRunner;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Without a JWT secret the service fails closed: neither tokens nor identity headers authenticate.
 */
@RunWith(SpringRunner.class)
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@TestPropertySource(properties = "otterworks.security.jwt-secret=")
public class ReportMissingJwtSecretIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    public void everyReportRequestIsRejected() throws Exception {
        mockMvc.perform(get("/api/v1/reports")
                        .header("X-User-ID", "someone")
                        .header("X-User-Roles", "ADMIN"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/v1/reports/1")
                        .header(HttpHeaders.AUTHORIZATION, TestJwt.adminBearer("someone")))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(delete("/api/v1/reports/1")
                        .header(HttpHeaders.AUTHORIZATION, TestJwt.bearer("someone")))
                .andExpect(status().isUnauthorized());
    }

    @Test
    public void healthStaysPublic() throws Exception {
        mockMvc.perform(get("/health")).andExpect(status().isOk());
    }
}
