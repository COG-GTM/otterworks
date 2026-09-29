package com.otterworks.userpreferences;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(properties = "spring.datasource.url=jdbc:h2:mem:userpreferences-fullcontext;DB_CLOSE_DELAY=-1;MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE")
@AutoConfigureMockMvc
@AutoConfigureObservability
class UserPreferencesServiceApplicationTest {

    @Autowired private MockMvc mockMvc;

    @Test
    void healthReportsServiceNameAndLegacyBanner() throws Exception {
        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.service").value("user-preferences-service"))
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
    void unknownUserGetsDefaultsAndPutPersists() throws Exception {
        mockMvc.perform(get("/api/preferences/ctx-user"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("light"))
                .andExpect(jsonPath("$.locale").value("en-US"))
                .andExpect(jsonPath("$.emailNotifications").value(true));
        mockMvc.perform(
                        put("/api/preferences/ctx-user")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"theme\":\"dark\",\"locale\":\"fr-FR\",\"emailNotifications\":false}"))
                .andExpect(status().isOk());
        mockMvc.perform(get("/api/preferences/ctx-user/"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("dark"));
    }

    @Test
    void validationFailureIsBadRequest() throws Exception {
        mockMvc.perform(
                        put("/api/preferences/ctx-user")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"theme\":\"\",\"locale\":\"en-US\"}"))
                .andExpect(status().isBadRequest());
    }
}
