package com.otterworks.legacyportal.qa;

import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;
import org.springframework.transaction.annotation.Transactional;

/** QA audit: HTTP contract of all three bounded contexts; each test rolls back its writes. */
@SpringBootTest
@AutoConfigureMockMvc
@Transactional
class QaPortalApiTest {

    @Autowired private MockMvc mockMvc;
    @Autowired private ObjectMapper objectMapper;

    private ResultActions postJson(String path, String json) throws Exception {
        return mockMvc.perform(post(path).contentType(MediaType.APPLICATION_JSON).content(json));
    }

    private ResultActions putJson(String path, String json) throws Exception {
        return mockMvc.perform(put(path).contentType(MediaType.APPLICATION_JSON).content(json));
    }

    private long createAnnouncement(String title, boolean published) throws Exception {
        String body =
                postJson(
                                "/api/announcements",
                                "{\"title\":\"" + title + "\",\"body\":\"b\",\"published\":"
                                        + published + "}")
                        .andExpect(status().isCreated())
                        .andReturn()
                        .getResponse()
                        .getContentAsString();
        JsonNode node = objectMapper.readTree(body);
        return node.get("id").asLong();
    }

    // --- health ---------------------------------------------------------------

    @Test
    void healthBannerIsInterpolated() throws Exception {
        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.banner").value(containsString("on-prem")))
                .andExpect(
                        jsonPath("$.banner")
                                .value(containsString("portal-support@otterworks.example")));
    }

    // --- announcements ------------------------------------------------------------

    @Test
    void createReturnsPersistedAnnouncement() throws Exception {
        postJson("/api/announcements", "{\"title\":\"QA\",\"body\":\"hello\",\"published\":true}")
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.title").value("QA"))
                .andExpect(jsonPath("$.published").value(true))
                .andExpect(jsonPath("$.createdAt").isNotEmpty());
    }

    @Test
    void draftIsHiddenUntilPublished() throws Exception {
        long id = createAnnouncement("qa-draft", false);
        mockMvc.perform(get("/api/announcements"))
                .andExpect(jsonPath("$[?(@.title == 'qa-draft')]").isEmpty());

        mockMvc.perform(post("/api/announcements/" + id + "/publish"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.published").value(true));
        mockMvc.perform(get("/api/announcements"))
                .andExpect(jsonPath("$[?(@.title == 'qa-draft')]").isNotEmpty());
    }

    @Test
    void publishIsIdempotent() throws Exception {
        long id = createAnnouncement("qa-twice", true);
        mockMvc.perform(post("/api/announcements/" + id + "/publish"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.published").value(true));
    }

    @Test
    void getByIdReturnsAnnouncement() throws Exception {
        long id = createAnnouncement("qa-get", true);
        mockMvc.perform(get("/api/announcements/" + id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(id));
    }

    @Test
    void unknownAnnouncementIs404WithErrorBody() throws Exception {
        mockMvc.perform(get("/api/announcements/987654321"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("Not Found"));
    }

    @Test
    void publishUnknownAnnouncementIs404() throws Exception {
        mockMvc.perform(post("/api/announcements/987654321/publish"))
                .andExpect(status().isNotFound());
    }

    @ParameterizedTest
    @ValueSource(
            strings = {
                "{\"title\":\"\",\"body\":\"b\"}",
                "{\"title\":\"t\",\"body\":\" \"}",
                "{\"body\":\"b\"}",
                "{\"title\":\"t\"}"
            })
    void createValidatesRequiredFields(String json) throws Exception {
        postJson("/api/announcements", json).andExpect(status().isBadRequest());
    }

    @Test
    void createRejectsOverlongTitle() throws Exception {
        String title = "x".repeat(201);
        postJson("/api/announcements", "{\"title\":\"" + title + "\",\"body\":\"b\"}")
                .andExpect(status().isBadRequest());
    }

    @Test
    void createAcceptsTitleAtLimit() throws Exception {
        String title = "x".repeat(200);
        postJson("/api/announcements", "{\"title\":\"" + title + "\",\"body\":\"b\"}")
                .andExpect(status().isCreated());
    }

    @Test
    void malformedJsonIs400() throws Exception {
        postJson("/api/announcements", "{not json").andExpect(status().isBadRequest());
    }

    @Disabled(
            "QA-BILL-09: GET /api/announcements/{id} returns unpublished drafts to any caller"
                    + " (AnnouncementController#get has no published check)")
    @Test
    void draftIsNotReadableById() throws Exception {
        long id = createAnnouncement("qa-secret-draft", false);
        mockMvc.perform(get("/api/announcements/" + id)).andExpect(status().isNotFound());
    }

    // --- feedback -------------------------------------------------------------------

    @ParameterizedTest
    @ValueSource(ints = {1, 5})
    void feedbackAcceptsBoundaryRatings(int rating) throws Exception {
        postJson(
                        "/api/feedback",
                        "{\"userId\":\"qa-u\",\"rating\":" + rating + ",\"message\":\"m\"}")
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.rating").value(rating));
    }

    @ParameterizedTest
    @ValueSource(ints = {0, 6, -1})
    void feedbackRejectsOutOfRangeRatings(int rating) throws Exception {
        postJson(
                        "/api/feedback",
                        "{\"userId\":\"qa-u\",\"rating\":" + rating + ",\"message\":\"m\"}")
                .andExpect(status().isBadRequest());
    }

    @Test
    void feedbackRequiresMessageAndUser() throws Exception {
        postJson("/api/feedback", "{\"userId\":\"qa-u\",\"rating\":3,\"message\":\"\"}")
                .andExpect(status().isBadRequest());
        postJson("/api/feedback", "{\"rating\":3,\"message\":\"m\"}")
                .andExpect(status().isBadRequest());
    }

    @Test
    void feedbackListIsScopedToUserNewestFirst() throws Exception {
        postJson("/api/feedback", "{\"userId\":\"qa-a\",\"rating\":2,\"message\":\"old\"}");
        Thread.sleep(5);
        postJson("/api/feedback", "{\"userId\":\"qa-a\",\"rating\":4,\"message\":\"new\"}");
        postJson("/api/feedback", "{\"userId\":\"qa-b\",\"rating\":5,\"message\":\"other\"}");

        mockMvc.perform(get("/api/feedback").param("userId", "qa-a"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].message").value("new"))
                .andExpect(jsonPath("$[1].message").value("old"));
    }

    @Test
    void feedbackListRequiresUserId() throws Exception {
        mockMvc.perform(get("/api/feedback")).andExpect(status().isBadRequest());
    }

    @Test
    void averageRatingReflectsSubmissions() throws Exception {
        postJson("/api/feedback", "{\"userId\":\"qa-avg\",\"rating\":5,\"message\":\"m\"}");
        mockMvc.perform(get("/api/feedback/average-rating"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.averageRating").isNumber());
    }

    // --- user preferences ----------------------------------------------------------

    @Test
    void preferencesDefaultForUnknownUser() throws Exception {
        mockMvc.perform(get("/api/preferences/qa-new"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.userId").value("qa-new"))
                .andExpect(jsonPath("$.theme").value("light"))
                .andExpect(jsonPath("$.locale").value("en-US"))
                .andExpect(jsonPath("$.emailNotifications").value(true));
    }

    @Test
    void preferencesRoundTrip() throws Exception {
        putJson(
                        "/api/preferences/qa-pref",
                        "{\"theme\":\"dark\",\"locale\":\"fr-FR\",\"emailNotifications\":false}")
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.theme").value("dark"));
        mockMvc.perform(get("/api/preferences/qa-pref"))
                .andExpect(jsonPath("$.theme").value("dark"))
                .andExpect(jsonPath("$.locale").value("fr-FR"))
                .andExpect(jsonPath("$.emailNotifications").value(false));
    }

    @Test
    void preferencesAreIsolatedPerUser() throws Exception {
        putJson("/api/preferences/qa-one", "{\"theme\":\"dark\",\"locale\":\"de-DE\"}")
                .andExpect(status().isOk());
        mockMvc.perform(get("/api/preferences/qa-two"))
                .andExpect(jsonPath("$.theme").value("light"));
    }

    @ParameterizedTest
    @ValueSource(
            strings = {
                "{\"theme\":\"\",\"locale\":\"en-US\"}",
                "{\"theme\":\"dark\"}",
                "{\"theme\":\"aaaaaaaaaaaaaaaaaaaaa\",\"locale\":\"en-US\"}"
            })
    void preferencesValidateBody(String json) throws Exception {
        putJson("/api/preferences/qa-bad", json).andExpect(status().isBadRequest());
    }
}
