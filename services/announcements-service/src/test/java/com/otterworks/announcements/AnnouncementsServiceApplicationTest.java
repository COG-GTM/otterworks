package com.otterworks.announcements;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(properties = "spring.datasource.url=jdbc:h2:mem:announcements-fullcontext;DB_CLOSE_DELAY=-1;MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE")
@AutoConfigureMockMvc
@AutoConfigureObservability
class AnnouncementsServiceApplicationTest {

    @Autowired private MockMvc mockMvc;

    @Test
    void healthReportsServiceNameAndLegacyBanner() throws Exception {
        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.service").value("announcements-service"))
                .andExpect(
                        jsonPath("$.banner")
                                .value("OtterWorks Portal (on-prem) - contact portal-support@otterworks.example"));
    }

    @Test
    void probesAndMetricsAreExposed() throws Exception {
        mockMvc.perform(get("/actuator/health/liveness")).andExpect(status().isOk());
        mockMvc.perform(get("/actuator/health/readiness")).andExpect(status().isOk());
        mockMvc.perform(get("/actuator/prometheus")).andExpect(status().isOk());
    }

    @Test
    void createThenPublishRoundTrips() throws Exception {
        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"title\":\"Draft\",\"body\":\"b\",\"published\":false}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.published").value(false));
        mockMvc.perform(post("/api/announcements/1/publish"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.published").value(true));
        mockMvc.perform(get("/api/announcements/424242"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.message").value("announcement 424242 not found"));
    }

    @Test
    void validationFailureIsBadRequest() throws Exception {
        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"title\":\" \",\"body\":\"b\"}"))
                .andExpect(status().isBadRequest());
    }
}
