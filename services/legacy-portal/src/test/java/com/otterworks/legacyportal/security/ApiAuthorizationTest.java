package com.otterworks.legacyportal.security;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.nimbusds.jose.JWSAlgorithm;
import com.otterworks.legacyportal.TestTokens;
import com.otterworks.legacyportal.announcements.AnnouncementService;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.transaction.annotation.Transactional;

/** End-to-end authorization through the real filter chain and HMAC token decoder. */
@SpringBootTest(properties = "legacy-portal.security.jwt-secret=" + TestTokens.SECRET)
@AutoConfigureMockMvc
@Transactional
class ApiAuthorizationTest {

    @Autowired private MockMvc mockMvc;
    @Autowired private AnnouncementService announcements;

    private static MockHttpServletRequestBuilder bearer(
            MockHttpServletRequestBuilder request, String token) {
        return request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
    }

    private static String userToken(String id) {
        return TestTokens.access(id, "USER");
    }

    private static String adminToken() {
        return TestTokens.access("admin-1", "ADMIN");
    }

    private static MockHttpServletRequestBuilder createAnnouncement(String path, boolean published) {
        return post(path)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"title\":\"t\",\"body\":\"b\",\"published\":" + published + "}");
    }

    @Test
    void anonymousCallersAreRejectedOnEveryApiRoute() throws Exception {
        mockMvc.perform(createAnnouncement("/api/announcements", true))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(post("/api/announcements/1/publish")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/announcements").param("publishedOnly", "false"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/announcements/1")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/feedback").param("userId", "victim"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"victim\",\"rating\":1,\"message\":\"x\"}"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/feedback/average-rating")).andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/preferences/victim")).andExpect(status().isUnauthorized());
    }

    @Test
    void invalidTokensAreRejected() throws Exception {
        String forged =
                TestTokens.sign(
                        "attacker-chosen-secret-attacker-chosen-secret-xyz",
                        JWSAlgorithm.HS384,
                        "admin-1",
                        "access",
                        List.of("ADMIN"),
                        3600);
        String refresh =
                TestTokens.sign(
                        TestTokens.SECRET, JWSAlgorithm.HS384, "admin-1", "refresh", List.of(), 3600);
        String expired =
                TestTokens.sign(
                        TestTokens.SECRET,
                        JWSAlgorithm.HS384,
                        "admin-1",
                        "access",
                        List.of("ADMIN"),
                        -3600);
        String wrongAlgorithm =
                TestTokens.sign(
                        TestTokens.SECRET,
                        JWSAlgorithm.HS256,
                        "admin-1",
                        "access",
                        List.of("ADMIN"),
                        3600);
        for (String token : List.of(forged, refresh, expired, wrongAlgorithm, "not-a-jwt")) {
            mockMvc.perform(bearer(createAnnouncement("/api/announcements", true), token))
                    .andExpect(status().isUnauthorized());
        }
    }

    @Test
    void onlyAdminsMayCreateOrPublishAnnouncements() throws Exception {
        Long draft = announcements.create("draft", "body", false).getId();

        mockMvc.perform(bearer(createAnnouncement("/api/announcements", true), userToken("u1")))
                .andExpect(status().isForbidden());
        mockMvc.perform(bearer(createAnnouncement("/api/announcements/", true), userToken("u1")))
                .andExpect(status().isForbidden());
        mockMvc.perform(bearer(post("/api/announcements/" + draft + "/publish"), userToken("u1")))
                .andExpect(status().isForbidden());

        mockMvc.perform(bearer(createAnnouncement("/api/announcements", true), adminToken()))
                .andExpect(status().isCreated());
        mockMvc.perform(bearer(post("/api/announcements/" + draft + "/publish"), adminToken()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.published").value(true));
    }

    @Test
    void draftsAreHiddenFromNonAdmins() throws Exception {
        Long draft = announcements.create("secret draft", "body", false).getId();

        mockMvc.perform(
                        bearer(get("/api/announcements"), userToken("u1"))
                                .param("publishedOnly", "false"))
                .andExpect(status().isForbidden());
        mockMvc.perform(bearer(get("/api/announcements/" + draft), userToken("u1")))
                .andExpect(status().isNotFound());

        mockMvc.perform(
                        bearer(get("/api/announcements"), adminToken())
                                .param("publishedOnly", "false"))
                .andExpect(status().isOk());
        mockMvc.perform(bearer(get("/api/announcements/" + draft), adminToken()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("secret draft"));
    }

    @Test
    void feedbackIsBoundToTheAuthenticatedUser() throws Exception {
        mockMvc.perform(
                        bearer(post("/api/feedback"), userToken("attacker"))
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"userId\":\"victim\",\"rating\":1,\"message\":\"forged\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.userId").value("attacker"));

        mockMvc.perform(bearer(get("/api/feedback"), userToken("victim")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
        mockMvc.perform(bearer(get("/api/feedback"), userToken("attacker")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].userId").value("attacker"));

        mockMvc.perform(
                        bearer(get("/api/feedback"), userToken("attacker")).param("userId", "victim"))
                .andExpect(status().isForbidden());
        mockMvc.perform(bearer(get("/api/feedback"), adminToken()).param("userId", "attacker"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].message").value("forged"));
    }
}
