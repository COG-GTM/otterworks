package com.otterworks.legacyportal.userpreferences;

import static org.assertj.core.api.Assertions.assertThat;
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

@WebMvcTest(UserPreferenceController.class)
class UserPreferenceControllerTest {

    @Autowired private MockMvc mockMvc;

    @MockBean private UserPreferenceService service;

    @Test
    void getReturnsTheStoredPreference() throws Exception {
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
    void getFallsBackToTheServiceDefaults() throws Exception {
        when(service.getOrDefault("newcomer"))
                .thenReturn(new UserPreference("newcomer", "light", "en-US", true));

        mockMvc.perform(get("/api/preferences/newcomer"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("light"))
                .andExpect(jsonPath("$.locale").value("en-US"))
                .andExpect(jsonPath("$.emailNotifications").value(true));
    }

    @Test
    void updatePersistsEveryFieldFromThePayload() throws Exception {
        when(service.save("u1", "dark", "de-DE", true))
                .thenReturn(new UserPreference("u1", "dark", "de-DE", true));

        mockMvc.perform(
                        put("/api/preferences/u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"theme\":\"dark\",\"locale\":\"de-DE\","
                                                + "\"emailNotifications\":true}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value("u1"))
                .andExpect(jsonPath("$.theme").value("dark"))
                .andExpect(jsonPath("$.locale").value("de-DE"))
                .andExpect(jsonPath("$.emailNotifications").value(true));

        verify(service).save("u1", "dark", "de-DE", true);
    }

    @Test
    void updateDefaultsEmailNotificationsToFalseWhenOmitted() throws Exception {
        when(service.save("u1", "dark", "en-US", false))
                .thenReturn(new UserPreference("u1", "dark", "en-US", false));

        mockMvc.perform(
                        put("/api/preferences/u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"theme\":\"dark\",\"locale\":\"en-US\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.emailNotifications").value(false));

        verify(service).save("u1", "dark", "en-US", false);
    }

    @Test
    void updateRejectsABlankTheme() throws Exception {
        mockMvc.perform(
                        put("/api/preferences/u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"theme\":\"  \",\"locale\":\"en-US\","
                                                + "\"emailNotifications\":true}"))
                .andExpect(status().isBadRequest());

        verify(service, never()).save(anyString(), anyString(), anyString(), anyBoolean());
    }

    @Test
    void updateRejectsAnOverlongLocale() throws Exception {
        mockMvc.perform(
                        put("/api/preferences/u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"theme\":\"dark\",\"locale\":\"en-US-with-a-far-too-"
                                                + "long-tag\",\"emailNotifications\":true}"))
                .andExpect(status().isBadRequest());

        verify(service, never()).save(anyString(), anyString(), anyString(), anyBoolean());
    }

    @Test
    void requestPayloadAccessorsRoundTrip() {
        UserPreferenceController.UpdatePreferenceRequest request =
                new UserPreferenceController.UpdatePreferenceRequest();
        request.setTheme("dark");
        request.setLocale("nl-NL");
        request.setEmailNotifications(true);

        assertThat(request.getTheme()).isEqualTo("dark");
        assertThat(request.getLocale()).isEqualTo("nl-NL");
        assertThat(request.isEmailNotifications()).isTrue();
    }
}
