package com.otterworks.legacyportal.userpreferences;

import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

/** Web-layer tests for the user-preferences module. */
@WebMvcTest(UserPreferenceController.class)
class UserPreferenceControllerTest {

    @Autowired private MockMvc mockMvc;

    @MockBean private UserPreferenceService service;

    @Test
    void getReturnsStoredPreferences() throws Exception {
        when(service.getOrDefault("u1"))
                .thenReturn(new UserPreference("u1", "dark", "fr-FR", false));

        mockMvc.perform(get("/api/preferences/u1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value("u1"))
                .andExpect(jsonPath("$.theme").value("dark"))
                .andExpect(jsonPath("$.locale").value("fr-FR"))
                .andExpect(jsonPath("$.emailNotifications").value(false));
    }

    @Test
    void updatePersistsEveryFieldFromTheRequestBody() throws Exception {
        when(service.save("u1", "dark", "de-DE", true))
                .thenReturn(new UserPreference("u1", "dark", "de-DE", true));

        mockMvc.perform(
                        put("/api/preferences/u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"theme\":\"dark\",\"locale\":\"de-DE\",\"emailNotifications\":true}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("dark"))
                .andExpect(jsonPath("$.locale").value("de-DE"))
                .andExpect(jsonPath("$.emailNotifications").value(true));

        verify(service).save("u1", "dark", "de-DE", true);
    }

    @Test
    void updateRejectsBlankTheme() throws Exception {
        mockMvc.perform(
                        put("/api/preferences/u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"theme\":\"\",\"locale\":\"en-US\",\"emailNotifications\":true}"))
                .andExpect(status().isBadRequest());

        verify(service, never()).save(anyString(), anyString(), anyString(), anyBoolean());
    }

    @Test
    void updateRejectsLocaleLongerThanTheColumn() throws Exception {
        mockMvc.perform(
                        put("/api/preferences/u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"theme\":\"light\",\"locale\":\"this-locale-is-far-too-long\",\"emailNotifications\":false}"))
                .andExpect(status().isBadRequest());

        verify(service, never()).save(anyString(), anyString(), anyString(), anyBoolean());
    }
}
