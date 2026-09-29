package com.otterworks.feedback;

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

@SpringBootTest(properties = "spring.datasource.url=jdbc:h2:mem:feedback-fullcontext;DB_CLOSE_DELAY=-1;MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE")
@AutoConfigureMockMvc
@AutoConfigureObservability
class FeedbackServiceApplicationTest {

    @Autowired private MockMvc mockMvc;

    @Test
    void healthReportsServiceNameAndLegacyBanner() throws Exception {
        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.service").value("feedback-service"))
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
    void submitListAndAverage() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"ctx\",\"rating\":4,\"message\":\"ok\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.rating").value(4));
        mockMvc.perform(get("/api/feedback").param("userId", "ctx"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].message").value("ok"));
        mockMvc.perform(get("/api/feedback/average-rating/"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.averageRating").value(4.0));
    }

    @Test
    void outOfRangeRatingIsBadRequest() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"ctx\",\"rating\":6,\"message\":\"m\"}"))
                .andExpect(status().isBadRequest());
    }
}
