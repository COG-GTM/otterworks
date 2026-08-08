package com.otterworks.legacyportal.feedback;

import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
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
import org.springframework.test.web.servlet.MockMvc;

/** Web-layer tests for the feedback module: routing, validation, and JSON mapping. */
@WebMvcTest(FeedbackController.class)
class FeedbackControllerTest {

    @Autowired private MockMvc mockMvc;

    @MockBean private FeedbackService service;

    @Test
    void submitReturnsCreatedWithMappedBody() throws Exception {
        when(service.submit("u1", 5, "great")).thenReturn(new Feedback("u1", 5, "great"));

        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"userId\":\"u1\",\"rating\":5,\"message\":\"great\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.userId").value("u1"))
                .andExpect(jsonPath("$.rating").value(5))
                .andExpect(jsonPath("$.message").value("great"))
                .andExpect(jsonPath("$.createdAt").exists());

        verify(service).submit("u1", 5, "great");
    }

    @Test
    void submitRejectsBlankUserIdBeforeReachingTheService() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"\",\"rating\":3,\"message\":\"hi\"}"))
                .andExpect(status().isBadRequest());

        verify(service, org.mockito.Mockito.never()).submit(anyString(), anyInt(), anyString());
    }

    @Test
    void submitRejectsRatingAboveMaximum() throws Exception {
        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"u1\",\"rating\":6,\"message\":\"hi\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void serviceRejectionIsTranslatedToBadRequest() throws Exception {
        when(service.submit(eq("u1"), eq(4), anyString()))
                .thenThrow(new IllegalArgumentException("rating must be between 1 and 5"));

        mockMvc.perform(
                        post("/api/feedback")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"userId\":\"u1\",\"rating\":4,\"message\":\"hi\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("Bad Request"))
                .andExpect(jsonPath("$.message").value("rating must be between 1 and 5"));
    }

    @Test
    void listForUserReturnsEveryEntry() throws Exception {
        when(service.listForUser("u1"))
                .thenReturn(
                        Arrays.asList(new Feedback("u1", 5, "great"), new Feedback("u1", 2, "meh")));

        mockMvc.perform(get("/api/feedback").param("userId", "u1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].message").value("great"))
                .andExpect(jsonPath("$[1].rating").value(2));
    }

    @Test
    void listForUserReturnsEmptyArrayForUnknownUser() throws Exception {
        when(service.listForUser("nobody")).thenReturn(Collections.emptyList());

        mockMvc.perform(get("/api/feedback").param("userId", "nobody"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(0));
    }

    @Test
    void listForUserRequiresTheUserIdParameter() throws Exception {
        mockMvc.perform(get("/api/feedback")).andExpect(status().isBadRequest());
    }

    @Test
    void averageRatingIsExposedAsItsOwnResource() throws Exception {
        when(service.averageRating()).thenReturn(3.5);

        mockMvc.perform(get("/api/feedback/average-rating"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.averageRating").value(3.5));
    }
}
