package com.otterworks.legacyportal;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.otterworks.legacyportal.security.TestTokens;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

/** Full-context test: the whole modular monolith boots and every module's routes are wired. */
@SpringBootTest(properties = "legacy-portal.security.jwt-secret=" + TestTokens.SECRET)
@AutoConfigureMockMvc
@Transactional
class LegacyPortalApplicationTest {

    private static final String PREFS_BODY =
            "{\"theme\":\"dark\",\"locale\":\"fr-FR\",\"emailNotifications\":false}";

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
                                .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("admin-1", "ADMIN"))
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"title\":\"Release\",\"body\":\"v1 is out\",\"published\":true}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").isNumber());

        mockMvc.perform(get("/api/announcements").header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("u1")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].title").value("Release"));
    }

    @Test
    void preferencesModuleReturnsDefaults() throws Exception {
        mockMvc.perform(get("/api/preferences/newuser")
                        .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("newuser")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value("newuser"))
                .andExpect(jsonPath("$.theme").value("light"));
    }

    @Test
    void feedbackModuleValidatesRating() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("u1"))
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"rating\":9,\"message\":\"bad rating\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void apiRejectsAnonymousRequests() throws Exception {
        mockMvc.perform(get("/api/preferences/alice")).andExpect(status().isUnauthorized());
        mockMvc.perform(put("/api/preferences/alice")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(PREFS_BODY))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/feedback").param("userId", "alice"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/announcements")).andExpect(status().isUnauthorized());
    }

    @Test
    void apiRejectsForgedRefreshAndExpiredTokens() throws Exception {
        mockMvc.perform(get("/api/preferences/me")
                        .header(HttpHeaders.AUTHORIZATION,
                                "Bearer " + TestTokens.signedWith(
                                        "some-other-secret-that-is-long-enough-1234567890", "alice")))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/preferences/me")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.refresh("alice")))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/preferences/me")
                        .header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.expired("alice")))
                .andExpect(status().isUnauthorized());
    }

    @Test
    void preferencesAreScopedToTheCaller() throws Exception {
        String alice = TestTokens.bearer("alice");
        String mallory = TestTokens.bearer("mallory");

        mockMvc.perform(put("/api/preferences/me")
                        .header(HttpHeaders.AUTHORIZATION, alice)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(PREFS_BODY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value("alice"));

        mockMvc.perform(get("/api/preferences/alice").header(HttpHeaders.AUTHORIZATION, mallory))
                .andExpect(status().isForbidden());
        mockMvc.perform(put("/api/preferences/alice")
                        .header(HttpHeaders.AUTHORIZATION, mallory)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"theme\":\"light\",\"locale\":\"en-US\",\"emailNotifications\":true}"))
                .andExpect(status().isForbidden());

        mockMvc.perform(get("/api/preferences/me").header(HttpHeaders.AUTHORIZATION, alice))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("dark"))
                .andExpect(jsonPath("$.emailNotifications").value(false));
    }

    @Test
    void feedbackIsAttributedToAndReadableByTheCallerOnly() throws Exception {
        mockMvc.perform(post("/api/feedback")
                        .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("alice"))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"userId\":\"bob\",\"rating\":4,\"message\":\"nice\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.userId").value("alice"));

        mockMvc.perform(get("/api/feedback").header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("alice")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].userId").value("alice"));
        mockMvc.perform(get("/api/feedback")
                        .param("userId", "alice")
                        .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("mallory")))
                .andExpect(status().isForbidden());
        mockMvc.perform(get("/api/feedback")
                        .param("userId", "alice")
                        .header(HttpHeaders.AUTHORIZATION, TestTokens.bearer("admin-1", "ADMIN")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].userId").value("alice"));
    }

    @Test
    void onlyAdminsManageAnnouncementsAndSeeDrafts() throws Exception {
        String user = TestTokens.bearer("u1", "USER");
        String admin = TestTokens.bearer("admin-1", "ADMIN");

        mockMvc.perform(post("/api/announcements")
                        .header(HttpHeaders.AUTHORIZATION, user)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"Fake\",\"body\":\"phish\",\"published\":true}"))
                .andExpect(status().isForbidden());
        mockMvc.perform(post("/api/announcements/")
                        .header(HttpHeaders.AUTHORIZATION, user)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"Fake\",\"body\":\"phish\",\"published\":true}"))
                .andExpect(status().isForbidden());

        String draft = mockMvc.perform(post("/api/announcements")
                        .header(HttpHeaders.AUTHORIZATION, admin)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"title\":\"Draft\",\"body\":\"soon\",\"published\":false}"))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        String id = draft.replaceAll(".*\"id\":(\\d+).*", "$1");

        mockMvc.perform(get("/api/announcements/" + id).header(HttpHeaders.AUTHORIZATION, user))
                .andExpect(status().isNotFound());
        mockMvc.perform(get("/api/announcements").param("publishedOnly", "false")
                        .header(HttpHeaders.AUTHORIZATION, user))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[?(@.title == 'Draft')]").isEmpty());
        mockMvc.perform(post("/api/announcements/" + id + "/publish").header(HttpHeaders.AUTHORIZATION, user))
                .andExpect(status().isForbidden());
        mockMvc.perform(post("/api/announcements/" + id + "/publish/").header(HttpHeaders.AUTHORIZATION, user))
                .andExpect(status().isForbidden());
        mockMvc.perform(post("/api/announcements/" + id + "/publish").header(HttpHeaders.AUTHORIZATION, admin))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.published").value(true));
        mockMvc.perform(get("/api/announcements/" + id).header(HttpHeaders.AUTHORIZATION, user))
                .andExpect(status().isOk());
    }
}
