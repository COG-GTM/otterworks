package com.otterworks.legacyportal.feedback;

import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.Arrays;
import java.util.Collections;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(FeedbackController.class)
class FeedbackControllerTest {

    @Autowired private MockMvc mockMvc;

    @MockBean private FeedbackService service;

    private static Feedback feedback(long id, String userId, int rating, String message) {
        Feedback feedback = new Feedback(userId, rating, message);
        ReflectionTestUtils.setField(feedback, "id", id);
        return feedback;
    }

    @Test
    void submitReturnsCreatedWithPersistedFeedback() throws Exception {
        when(service.submit("u1", 4, "solid")).thenReturn(feedback(7L, "u1", 4, "solid"));

        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"userId\":\"u1\",\"rating\":4,\"message\":\"solid\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(7))
                .andExpect(jsonPath("$.userId").value("u1"))
                .andExpect(jsonPath("$.rating").value(4))
                .andExpect(jsonPath("$.message").value("solid"))
                .andExpect(jsonPath("$.createdAt").isNotEmpty());

        verify(service).submit("u1", 4, "solid");
    }

    @Test
    void submitRejectsRatingAboveTheAllowedMaximum() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"u1\",\"rating\":6,\"message\":\"nope\"}"))
                .andExpect(status().isBadRequest());

        verify(service, never()).submit(anyString(), anyInt(), anyString());
    }

    @Test
    void submitRejectsBlankUserIdAndBlankMessage() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"  \",\"rating\":3,\"message\":\"\"}"))
                .andExpect(status().isBadRequest());

        verify(service, never()).submit(anyString(), anyInt(), anyString());
    }

    @Test
    void serviceRejectionIsTranslatedToBadRequestBody() throws Exception {
        when(service.submit("u1", 3, "hi"))
                .thenThrow(new IllegalArgumentException("rating must be between 1 and 5"));

        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"u1\",\"rating\":3,\"message\":\"hi\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("Bad Request"))
                .andExpect(jsonPath("$.message").value("rating must be between 1 and 5"));
    }

    @Test
    void listForUserMapsEveryEntryToTheResponseShape() throws Exception {
        when(service.listForUser("u1"))
                .thenReturn(
                        Arrays.asList(
                                feedback(2L, "u1", 5, "newest"), feedback(1L, "u1", 2, "older")));

        mockMvc.perform(get("/api/feedback").param("userId", "u1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].id").value(2))
                .andExpect(jsonPath("$[0].message").value("newest"))
                .andExpect(jsonPath("$[1].rating").value(2));
    }

    @Test
    void listForUserWithoutFeedbackReturnsEmptyArray() throws Exception {
        when(service.listForUser("ghost")).thenReturn(Collections.emptyList());

        mockMvc.perform(get("/api/feedback").param("userId", "ghost"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void listForUserRequiresTheUserIdParameter() throws Exception {
        mockMvc.perform(get("/api/feedback")).andExpect(status().isBadRequest());

        verify(service, never()).listForUser(anyString());
    }

    @Test
    void averageRatingIsExposedAsANumber() throws Exception {
        when(service.averageRating()).thenReturn(3.5);

        mockMvc.perform(get("/api/feedback/average-rating"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.averageRating").value(3.5));
    }

    @Test
    void averageRatingIsZeroWhenNoFeedbackExists() throws Exception {
        when(service.averageRating()).thenReturn(0.0);

        mockMvc.perform(get("/api/feedback/average-rating"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.averageRating").value(0.0));
    }

    @Test
    void requestPayloadAccessorsRoundTrip() {
        FeedbackController.SubmitFeedbackRequest request =
                new FeedbackController.SubmitFeedbackRequest();
        request.setUserId("u9");
        request.setRating(2);
        request.setMessage("meh");

        org.assertj.core.api.Assertions.assertThat(request.getUserId()).isEqualTo("u9");
        org.assertj.core.api.Assertions.assertThat(request.getRating()).isEqualTo(2);
        org.assertj.core.api.Assertions.assertThat(request.getMessage()).isEqualTo("meh");
    }

    @Test
    void maximumLengthMessageIsAccepted() throws Exception {
        String message = String.join("", Collections.nCopies(2000, "x"));
        when(service.submit(eq("u1"), eq(5), anyString()))
                .thenReturn(feedback(11L, "u1", 5, message));

        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"userId\":\"u1\",\"rating\":5,\"message\":\""
                                                + message
                                                + "\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(11));
    }
}
