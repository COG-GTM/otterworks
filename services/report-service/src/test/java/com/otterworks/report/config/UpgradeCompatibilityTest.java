package com.otterworks.report.config;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.is;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.forwardedUrl;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
public class UpgradeCompatibilityTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    public void legacyApiDocsPathRemainsPublic() throws Exception {
        mockMvc.perform(get("/v2/api-docs"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.info.title", is("OtterWorks Report Service API")))
                .andExpect(jsonPath("$.paths['/api/v1/reports'].post").exists());
    }

    @Test
    public void swaggerUiRemainsPublic() throws Exception {
        mockMvc.perform(get("/swagger-ui/index.html"))
                .andExpect(status().isOk());
        mockMvc.perform(get("/swagger-ui/"))
                .andExpect(status().isOk())
                .andExpect(forwardedUrl("/swagger-ui/index.html"));
    }

    @Test
    public void securityHeadersAndStatelessHealthArePreserved() throws Exception {
        mockMvc.perform(get("/health/"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status", is("healthy")))
                .andExpect(header().string("X-Frame-Options", "DENY"))
                .andExpect(header().string("X-Content-Type-Options", "nosniff"))
                .andExpect(header().string("X-XSS-Protection", "1; mode=block"))
                .andExpect(header().doesNotExist("Set-Cookie"));
    }

    @Test
    public void trailingSlashListRemainsAnEmptyPublicResponse() throws Exception {
        mockMvc.perform(get("/api/v1/reports/").param("userId", "compatibility-empty"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.total", is(0)));
    }

    @Test
    public void invalidPublicRequestStillFailsValidationRatherThanCsrf() throws Exception {
        mockMvc.perform(post("/api/v1/reports/")
                        .contentType("application/json").content("{}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    public void unmatchedRoutesRemainForbidden() throws Exception {
        mockMvc.perform(get("/private"))
                .andExpect(status().isForbidden());
    }
}
