package com.otterworks.legacyportal.feedback;

import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.Arrays;
import java.util.Collections;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;

/** Web-layer tests for the feedback module: the service is mocked at the boundary. */
@WebMvcTest(FeedbackController.class)
class FeedbackControllerTest {

    private static final Instant CREATED_AT = Instant.parse("2024-01-01T00:00:00Z");

    @Autowired private MockMvc mockMvc;

    @MockBean private FeedbackService service;

    private static Feedback feedback(long id, String userId, int rating, String message) {
        Feedback feedback = new Feedback(userId, rating, message);
        ReflectionTestUtils.setField(feedback, "id", id);
        ReflectionTestUtils.setField(feedback, "createdAt", CREATED_AT);
        return feedback;
    }

    @Test
    void submitReturns201WithThePersistedFeedback() throws Exception {
        when(service.submit("u1", 5, "great")).thenReturn(feedback(7L, "u1", 5, "great"));

        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"u1\",\"rating\":5,\"message\":\"great\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(7))
                .andExpect(jsonPath("$.userId").value("u1"))
                .andExpect(jsonPath("$.rating").value(5))
                .andExpect(jsonPath("$.message").value("great"))
                .andExpect(jsonPath("$.createdAt").value("2024-01-01T00:00:00Z"));

        verify(service).submit("u1", 5, "great");
    }

    @ParameterizedTest
    @ValueSource(
            strings = {
                "{\"userId\":\"u1\",\"rating\":0,\"message\":\"too low\"}",
                "{\"userId\":\"u1\",\"rating\":6,\"message\":\"too high\"}",
                "{\"userId\":\"\",\"rating\":3,\"message\":\"blank user\"}",
                "{\"userId\":\"u1\",\"rating\":3,\"message\":\"   \"}"
            })
    void invalidPayloadsAreRejectedBeforeReachingTheService(String payload) throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(payload))
                .andExpect(status().isBadRequest());

        verify(service, never()).submit(anyString(), anyInt(), anyString());
    }

    @Test
    void serviceRejectionIsTranslatedToA400Problem() throws Exception {
        when(service.submit("u1", 5, "boom"))
                .thenThrow(new IllegalArgumentException("rating must be between 1 and 5"));

        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"u1\",\"rating\":5,\"message\":\"boom\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("Bad Request"))
                .andExpect(jsonPath("$.message").value("rating must be between 1 and 5"));
    }

    @Test
    void listForUserReturnsOnlyThatUsersFeedback() throws Exception {
        when(service.listForUser("u1"))
                .thenReturn(
                        Arrays.asList(feedback(2L, "u1", 4, "later"), feedback(1L, "u1", 2, "earlier")));

        mockMvc.perform(get("/api/feedback").param("userId", "u1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].id").value(2))
                .andExpect(jsonPath("$[0].message").value("later"))
                .andExpect(jsonPath("$[1].id").value(1))
                .andExpect(jsonPath("$[1].rating").value(2));

        verify(service).listForUser("u1");
    }

    @Test
    void listForUserReturnsAnEmptyArrayWhenThereIsNoFeedback() throws Exception {
        when(service.listForUser("ghost")).thenReturn(Collections.emptyList());

        mockMvc.perform(get("/api/feedback").param("userId", "ghost"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void missingUserIdParameterIsRejected() throws Exception {
        mockMvc.perform(get("/api/feedback")).andExpect(status().isBadRequest());

        verify(service, never()).listForUser(anyString());
    }

    @Test
    void averageRatingIsExposedAsANumber() throws Exception {
        when(service.averageRating()).thenReturn(4.25);

        mockMvc.perform(get("/api/feedback/average-rating"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.averageRating").value(4.25));
    }
}
