package com.otterworks.legacyportal.security;

import static org.hamcrest.Matchers.everyItem;
import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.is;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.otterworks.legacyportal.announcements.AnnouncementRepository;
import com.otterworks.legacyportal.announcements.AnnouncementService;
import com.otterworks.legacyportal.feedback.FeedbackRepository;
import com.otterworks.legacyportal.feedback.FeedbackService;
import com.otterworks.legacyportal.userpreferences.UserPreferenceRepository;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

@SpringBootTest
@AutoConfigureMockMvc
class ApiAuthorizationTest {

    private static final String ALICE = TestTokens.bearer("alice", "USER");
    private static final String MALLORY = TestTokens.bearer("mallory", "USER");
    private static final String ADMIN = TestTokens.bearer("admin-1", "USER", "ADMIN");

    @Autowired private MockMvc mockMvc;
    @Autowired private FeedbackService feedback;
    @Autowired private FeedbackRepository feedbackRepository;
    @Autowired private AnnouncementService announcements;
    @Autowired private AnnouncementRepository announcementRepository;
    @Autowired private UserPreferenceRepository preferenceRepository;

    @BeforeEach
    void seed() {
        cleanUp();
        feedback.submit("alice", 2, "private complaint about billing");
    }

    // The H2 database outlives each Spring context, so leave nothing behind for other test classes.
    @AfterEach
    void cleanUp() {
        feedbackRepository.deleteAll();
        announcementRepository.deleteAll();
        preferenceRepository.deleteAll();
    }

    @Test
    void anonymousCallersAreRejectedOnEveryApiRoute() throws Exception {
        MockHttpServletRequestBuilder[] requests = {
            get("/api/feedback").param("userId", "alice"),
            json(post("/api/feedback"), "{\"userId\":\"alice\",\"rating\":1,\"message\":\"forged\"}"),
            get("/api/feedback/average-rating"),
            get("/api/preferences/alice"),
            json(put("/api/preferences/alice"), "{\"theme\":\"dark\",\"locale\":\"en\"}"),
            get("/api/announcements"),
            get("/api/announcements/1"),
            json(post("/api/announcements"), "{\"title\":\"t\",\"body\":\"b\"}"),
            post("/api/announcements/1/publish"),
        };
        for (MockHttpServletRequestBuilder request : requests) {
            mockMvc.perform(request)
                    .andExpect(status().isUnauthorized())
                    .andExpect(header().string("WWW-Authenticate", "Bearer"));
        }
        mockMvc.perform(get("/api/feedback/average-rating").header("Authorization", "Bearer garbage"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(
                        get("/api/feedback")
                                .header("Authorization", "Bearer " + TestTokens.refresh("alice")))
                .andExpect(status().isUnauthorized());
        assertFeedbackCount("alice", 1);
    }

    @Test
    void healthProbesStayAnonymous() throws Exception {
        mockMvc.perform(get("/health")).andExpect(status().isOk());
        mockMvc.perform(get("/actuator/health")).andExpect(status().isOk());
    }

    @Test
    void feedbackListIsScopedToTheCaller() throws Exception {
        mockMvc.perform(get("/api/feedback").header("Authorization", ALICE))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(1)))
                .andExpect(jsonPath("$[0].userId").value("alice"));

        mockMvc.perform(get("/api/feedback").header("Authorization", MALLORY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(0)));

        mockMvc.perform(
                        get("/api/feedback").param("userId", "alice").header("Authorization", MALLORY))
                .andExpect(status().isForbidden());

        mockMvc.perform(get("/api/feedback").param("userId", "alice").header("Authorization", ADMIN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(1)));
    }

    @Test
    void feedbackIsFiledAsTheCallerAndCannotBeForged() throws Exception {
        mockMvc.perform(
                        json(post("/api/feedback"), "{\"userId\":\"alice\",\"rating\":1,\"message\":\"forged\"}")
                                .header("Authorization", MALLORY))
                .andExpect(status().isForbidden());
        assertFeedbackCount("alice", 1);

        mockMvc.perform(
                        json(post("/api/feedback"), "{\"rating\":4,\"message\":\"mine\"}")
                                .header("Authorization", MALLORY))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.userId").value("mallory"));

        mockMvc.perform(
                        json(post("/api/feedback"), "{\"userId\":\"mallory\",\"rating\":5,\"message\":\"also mine\"}")
                                .header("Authorization", MALLORY))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.userId").value("mallory"));

        mockMvc.perform(get("/api/feedback").header("Authorization", MALLORY))
                .andExpect(jsonPath("$", hasSize(2)))
                .andExpect(jsonPath("$[*].userId", everyItem(is("mallory"))));
    }

    @Test
    void preferencesAreBoundToTheCaller() throws Exception {
        mockMvc.perform(get("/api/preferences/alice").header("Authorization", ALICE))
                .andExpect(status().isOk());
        mockMvc.perform(get("/api/preferences/alice").header("Authorization", MALLORY))
                .andExpect(status().isForbidden());
        mockMvc.perform(get("/api/preferences/alice").header("Authorization", ADMIN))
                .andExpect(status().isOk());

        String body = "{\"theme\":\"dark\",\"locale\":\"en\",\"emailNotifications\":true}";
        mockMvc.perform(json(put("/api/preferences/alice"), body).header("Authorization", MALLORY))
                .andExpect(status().isForbidden());
        mockMvc.perform(json(put("/api/preferences/alice"), body).header("Authorization", ADMIN))
                .andExpect(status().isForbidden());
        mockMvc.perform(json(put("/api/preferences/alice"), body).header("Authorization", ALICE))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("dark"));
    }

    @Test
    void announcementWritesAndDraftsAreAdminOnly() throws Exception {
        String body = "{\"title\":\"Draft\",\"body\":\"not yet\",\"published\":false}";
        mockMvc.perform(json(post("/api/announcements"), body).header("Authorization", ALICE))
                .andExpect(status().isForbidden());

        long draftId = announcements.create("Draft", "not yet", false).getId();
        mockMvc.perform(get("/api/announcements/" + draftId).header("Authorization", ALICE))
                .andExpect(status().isNotFound());
        mockMvc.perform(
                        get("/api/announcements")
                                .param("publishedOnly", "false")
                                .header("Authorization", ALICE))
                .andExpect(status().isForbidden());
        mockMvc.perform(post("/api/announcements/" + draftId + "/publish").header("Authorization", ALICE))
                .andExpect(status().isForbidden());

        mockMvc.perform(json(post("/api/announcements"), body).header("Authorization", ADMIN))
                .andExpect(status().isCreated());
        mockMvc.perform(post("/api/announcements/" + draftId + "/publish").header("Authorization", ADMIN))
                .andExpect(status().isOk());
        mockMvc.perform(get("/api/announcements/" + draftId).header("Authorization", ALICE))
                .andExpect(status().isOk());
    }

    private void assertFeedbackCount(String userId, int expected) {
        org.assertj.core.api.Assertions.assertThat(feedback.listForUser(userId)).hasSize(expected);
    }

    private static MockHttpServletRequestBuilder json(MockHttpServletRequestBuilder request, String body) {
        return request.contentType(MediaType.APPLICATION_JSON).content(body);
    }
}
