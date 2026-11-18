package com.otterworks.legacyportal.feedback;

import static org.hamcrest.Matchers.hasSize;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
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
class FeedbackControllerTest {

    @Autowired private MockMvc mockMvc;
    @Autowired private FeedbackRepository repository;

    private void submit(String userId, int rating, String message) throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        String.format(
                                                "{\"userId\":\"%s\",\"rating\":%d,\"message\":\"%s\"}",
                                                userId, rating, message)))
                .andExpect(status().isCreated());
    }

    @Test
    void submitReturnsCreatedFeedback() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"fc-u1\",\"rating\":4,\"message\":\"nice\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").isNumber())
                .andExpect(jsonPath("$.userId").value("fc-u1"))
                .andExpect(jsonPath("$.rating").value(4))
                .andExpect(jsonPath("$.message").value("nice"))
                .andExpect(jsonPath("$.createdAt").exists());
    }

    @Test
    void listForUserReturnsOnlyThatUsersFeedback() throws Exception {
        submit("fc-list-a", 5, "first");
        submit("fc-list-a", 2, "second");
        submit("fc-list-b", 3, "other");

        mockMvc.perform(get("/api/feedback").param("userId", "fc-list-a"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(2)))
                .andExpect(jsonPath("$[*].userId").value(org.hamcrest.Matchers.everyItem(
                        org.hamcrest.Matchers.is("fc-list-a"))));
    }

    @Test
    void listForUserWithoutUserIdIsBadRequest() throws Exception {
        mockMvc.perform(get("/api/feedback")).andExpect(status().isBadRequest());
    }

    @Test
    void averageRatingReflectsAllFeedback() throws Exception {
        repository.deleteAll();
        submit("fc-avg-a", 5, "great");
        submit("fc-avg-b", 2, "meh");

        mockMvc.perform(get("/api/feedback/average-rating"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.averageRating").value(3.5));
    }

    @Test
    void averageRatingIsZeroWithNoFeedback() throws Exception {
        repository.deleteAll();

        mockMvc.perform(get("/api/feedback/average-rating"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.averageRating").value(0.0));
    }

    @Test
    void submitRejectsRatingBelowRange() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"u\",\"rating\":0,\"message\":\"m\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void submitRejectsBlankMessage() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"u\",\"rating\":3,\"message\":\"\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void submitRejectsMissingUserId() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"rating\":3,\"message\":\"m\"}"))
                .andExpect(status().isBadRequest());
    }
}
