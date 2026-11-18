package com.otterworks.legacyportal.userpreferences;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

@SpringBootTest
@AutoConfigureMockMvc
@Transactional
class UserPreferenceControllerTest {

    @Autowired private MockMvc mockMvc;

    @Test
    void getUnknownUserReturnsDefaults() throws Exception {
        mockMvc.perform(get("/api/preferences/pc-new"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value("pc-new"))
                .andExpect(jsonPath("$.theme").value("light"))
                .andExpect(jsonPath("$.locale").value("en-US"))
                .andExpect(jsonPath("$.emailNotifications").value(true));
    }

    @Test
    void putPersistsPreferencesAndGetReturnsThem() throws Exception {
        mockMvc.perform(
                        put("/api/preferences/pc-u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"theme\":\"dark\",\"locale\":\"de-DE\",\"emailNotifications\":false}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value("pc-u1"))
                .andExpect(jsonPath("$.theme").value("dark"))
                .andExpect(jsonPath("$.locale").value("de-DE"))
                .andExpect(jsonPath("$.emailNotifications").value(false));

        mockMvc.perform(get("/api/preferences/pc-u1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("dark"))
                .andExpect(jsonPath("$.locale").value("de-DE"))
                .andExpect(jsonPath("$.emailNotifications").value(false));
    }

    @Test
    void putOverwritesExistingPreferences() throws Exception {
        mockMvc.perform(
                        put("/api/preferences/pc-u2")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"theme\":\"dark\",\"locale\":\"fr-FR\",\"emailNotifications\":false}"))
                .andExpect(status().isOk());

        mockMvc.perform(
                        put("/api/preferences/pc-u2")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"theme\":\"light\",\"locale\":\"en-GB\",\"emailNotifications\":true}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("light"))
                .andExpect(jsonPath("$.locale").value("en-GB"))
                .andExpect(jsonPath("$.emailNotifications").value(true));
    }

    @Test
    void putRejectsBlankTheme() throws Exception {
        mockMvc.perform(
                        put("/api/preferences/pc-u3")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"theme\":\"\",\"locale\":\"en-US\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void putRejectsOverlongLocale() throws Exception {
        mockMvc.perform(
                        put("/api/preferences/pc-u4")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"theme\":\"dark\",\"locale\":\"" + "x".repeat(21) + "\"}"))
                .andExpect(status().isBadRequest());
    }
}
