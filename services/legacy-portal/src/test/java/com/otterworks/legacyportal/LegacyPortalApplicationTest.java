package com.otterworks.legacyportal;

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

/** Full-context test: the whole modular monolith boots and every module's routes are wired. */
@SpringBootTest
@AutoConfigureMockMvc
@Transactional
class LegacyPortalApplicationTest {

    @Autowired private MockMvc mockMvc;

    @Test
    void healthEndpointReportsUp() throws Exception {
        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.service").value("legacy-portal"));
    }

    @Test
    void actuatorHealthIsUp() throws Exception {
        mockMvc.perform(get("/actuator/health")).andExpect(status().isOk());
    }

    @Test
    void announcementsModuleRoundTrips() throws Exception {
        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"title\":\"Release\",\"body\":\"v1 is out\",\"published\":true}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").isNumber());

        mockMvc.perform(get("/api/announcements"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].title").value("Release"));
    }

    @Test
    void preferencesModuleReturnsDefaults() throws Exception {
        mockMvc.perform(get("/api/preferences/newuser"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("light"));
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
    void trailingSlashMatchesTheMappedRoute() throws Exception {
        mockMvc.perform(get("/api/announcements/")).andExpect(status().isOk());
        mockMvc.perform(get("/api/preferences/newuser/"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value("newuser"));
    }
}
