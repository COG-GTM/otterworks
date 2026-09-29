package com.otterworks.feedback;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

/** Full-context test: the service boots on H2 with its Flyway schema and its routes are wired. */
@SpringBootTest
@AutoConfigureMockMvc
@Transactional
class FeedbackServiceApplicationTest {

    @Autowired private MockMvc mockMvc;

    @Test
    void healthEndpointReportsUp() throws Exception {
        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.service").value("feedback-service"));
    }

    @Test
    void actuatorHealthIsUp() throws Exception {
        mockMvc.perform(get("/actuator/health")).andExpect(status().isOk());
    }

    @Test
    void feedbackModuleValidatesRating() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"userId\":\"u1\",\"rating\":9,\"message\":\"bad rating\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void averageRatingOfAnEmptyTableIsZero() throws Exception {
        mockMvc.perform(get("/api/feedback/average-rating"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.averageRating").value(0.0));
    }

    @Test
    void trailingSlashMatchesTheMappedRoute() throws Exception {
        mockMvc.perform(get("/api/feedback/average-rating/"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.averageRating").isNumber());
    }
}
