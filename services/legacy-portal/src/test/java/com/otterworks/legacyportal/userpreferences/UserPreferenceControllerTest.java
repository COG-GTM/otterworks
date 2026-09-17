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
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

/** Web-layer tests for the user-preferences module: the service is mocked at the boundary. */
@WebMvcTest(UserPreferenceController.class)
class UserPreferenceControllerTest {

    @Autowired private MockMvc mockMvc;

    @MockBean private UserPreferenceService service;

    @Test
    void getExposesEveryStoredPreferenceField() throws Exception {
        when(service.getOrDefault("u1"))
                .thenReturn(new UserPreference("u1", "dark", "fr-FR", false));

        mockMvc.perform(get("/api/preferences/u1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value("u1"))
                .andExpect(jsonPath("$.theme").value("dark"))
                .andExpect(jsonPath("$.locale").value("fr-FR"))
                .andExpect(jsonPath("$.emailNotifications").value(false));

        verify(service).getOrDefault("u1");
    }

    @Test
    void getFallsBackToTheServiceDefaultsForAnUnknownUser() throws Exception {
        when(service.getOrDefault("ghost"))
                .thenReturn(
                        new UserPreference(
                                "ghost",
                                UserPreferenceService.DEFAULT_THEME,
                                UserPreferenceService.DEFAULT_LOCALE,
                                true));

        mockMvc.perform(get("/api/preferences/ghost"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("light"))
                .andExpect(jsonPath("$.locale").value("en-US"))
                .andExpect(jsonPath("$.emailNotifications").value(true));
    }

    @Test
    void updatePassesEveryFieldToTheServiceAndReturnsTheResult() throws Exception {
        when(service.save("u1", "dark", "de-DE", true))
                .thenReturn(new UserPreference("u1", "dark", "de-DE", true));

        mockMvc.perform(
                        put("/api/preferences/u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"theme\":\"dark\",\"locale\":\"de-DE\",\"emailNotifications\":true}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value("u1"))
                .andExpect(jsonPath("$.theme").value("dark"))
                .andExpect(jsonPath("$.locale").value("de-DE"))
                .andExpect(jsonPath("$.emailNotifications").value(true));

        verify(service).save("u1", "dark", "de-DE", true);
    }

    @Test
    void emailNotificationsDefaultsToFalseWhenOmitted() throws Exception {
        when(service.save("u1", "light", "en-US", false))
                .thenReturn(new UserPreference("u1", "light", "en-US", false));

        mockMvc.perform(
                        put("/api/preferences/u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"theme\":\"light\",\"locale\":\"en-US\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.emailNotifications").value(false));

        verify(service).save("u1", "light", "en-US", false);
    }

    @ParameterizedTest
    @ValueSource(
            strings = {
                "{\"theme\":\"\",\"locale\":\"en-US\"}",
                "{\"theme\":\"light\",\"locale\":\"   \"}",
                "{\"locale\":\"en-US\"}",
                "{\"theme\":\"aaaaaaaaaaaaaaaaaaaaaa\",\"locale\":\"en-US\"}"
            })
    void invalidPayloadsAreRejectedBeforeReachingTheService(String payload) throws Exception {
        mockMvc.perform(
                        put("/api/preferences/u1")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(payload))
                .andExpect(status().isBadRequest());

        verify(service, never()).save(anyString(), anyString(), anyString(), anyBoolean());
    }
}
