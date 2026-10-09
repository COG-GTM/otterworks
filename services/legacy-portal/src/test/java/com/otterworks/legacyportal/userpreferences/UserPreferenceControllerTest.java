package com.otterworks.legacyportal.userpreferences;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.otterworks.legacyportal.security.TestTokens;
import java.net.URI;
import java.time.Instant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

@SpringBootTest(properties = "legacyportal.security.jwt-secret=" + TestTokens.SECRET)
@AutoConfigureMockMvc
class UserPreferenceControllerTest {

    private static final String ALICE = "alice";
    private static final String BOB = "bob";
    private static final String DARK_NO_EMAIL =
            "{\"theme\":\"dark\",\"locale\":\"fr-FR\",\"emailNotifications\":false}";

    @Autowired private MockMvc mockMvc;
    @Autowired private UserPreferenceRepository repository;

    @BeforeEach
    void seedBob() {
        repository.deleteAll();
        repository.save(new UserPreference(BOB, "light", "en-US", true));
    }

    private static MockHttpServletRequestBuilder as(String subject, MockHttpServletRequestBuilder req) {
        return req.header(HttpHeaders.AUTHORIZATION, "Bearer " + TestTokens.accessToken(subject));
    }

    private static MockHttpServletRequestBuilder putPrefs(String userId) {
        return put("/api/preferences/" + userId)
                .contentType(MediaType.APPLICATION_JSON)
                .content(DARK_NO_EMAIL);
    }

    @Test
    void anonymousReadIsRejected() throws Exception {
        mockMvc.perform(get("/api/preferences/" + BOB)).andExpect(status().isUnauthorized());
    }

    @Test
    void anonymousWriteIsRejectedAndNothingChanges() throws Exception {
        mockMvc.perform(putPrefs(BOB)).andExpect(status().isUnauthorized());
        mockMvc.perform(putPrefs("brand-new-id")).andExpect(status().isUnauthorized());

        assertThat(repository.findById(BOB).orElseThrow().isEmailNotifications()).isTrue();
        assertThat(repository.findById("brand-new-id")).isEmpty();
    }

    @Test
    void invalidTokensAreRejected() throws Exception {
        String forged =
                TestTokens.sign(
                        "HS256",
                        "attacker-chosen-secret-0123456789abcdef",
                        TestTokens.claims(BOB, "access", Instant.now().plusSeconds(600)));
        String refresh =
                TestTokens.sign(
                        "HS256",
                        TestTokens.SECRET,
                        TestTokens.claims(BOB, "refresh", Instant.now().plusSeconds(600)));
        for (String token : new String[] {forged, refresh, "not-a-jwt"}) {
            mockMvc.perform(
                            get("/api/preferences/" + BOB)
                                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
                    .andExpect(status().isUnauthorized());
        }
    }

    @Test
    void userReadsOwnPreferences() throws Exception {
        mockMvc.perform(as(BOB, get("/api/preferences/" + BOB)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value(BOB))
                .andExpect(jsonPath("$.emailNotifications").value(true));
    }

    @Test
    void userUpdatesOwnPreferences() throws Exception {
        mockMvc.perform(as(ALICE, putPrefs(ALICE)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value(ALICE))
                .andExpect(jsonPath("$.theme").value("dark"))
                .andExpect(jsonPath("$.emailNotifications").value(false));

        assertThat(repository.findById(ALICE).orElseThrow().getLocale()).isEqualTo("fr-FR");
    }

    @Test
    void userCannotReadAnotherUsersPreferences() throws Exception {
        mockMvc.perform(as(ALICE, get("/api/preferences/" + BOB)))
                .andExpect(status().isForbidden());
    }

    @Test
    void userCannotOverwriteAnotherUsersPreferences() throws Exception {
        mockMvc.perform(as(ALICE, putPrefs(BOB))).andExpect(status().isForbidden());

        UserPreference bob = repository.findById(BOB).orElseThrow();
        assertThat(bob.getTheme()).isEqualTo("light");
        assertThat(bob.isEmailNotifications()).isTrue();
    }

    @Test
    void malformedUserIdIsRejected() throws Exception {
        mockMvc.perform(as(ALICE, get("/api/preferences/{id}", "bad id!")))
                .andExpect(status().isBadRequest());
    }

    @Test
    void firewallRejectedPathIsBadRequest() throws Exception {
        mockMvc.perform(as(ALICE, get(URI.create("/api/preferences/a%3Bdrop"))))
                .andExpect(status().isBadRequest());
    }

    @Test
    void otherModulesAndHealthStayPublic() throws Exception {
        mockMvc.perform(get("/health")).andExpect(status().isOk());
        mockMvc.perform(get("/api/announcements")).andExpect(status().isOk());
    }
}
