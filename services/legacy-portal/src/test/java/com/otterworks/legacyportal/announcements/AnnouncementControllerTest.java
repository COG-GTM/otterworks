package com.otterworks.legacyportal.announcements;

import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.Arrays;
import java.util.Collections;
import java.util.NoSuchElementException;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

/** Web-layer tests for the announcements module. */
@WebMvcTest(AnnouncementController.class)
class AnnouncementControllerTest {

    @Autowired private MockMvc mockMvc;

    @MockBean private AnnouncementService service;

    @Test
    void listDefaultsToPublishedOnly() throws Exception {
        when(service.listPublished())
                .thenReturn(Collections.singletonList(new Announcement("live", "body", true)));

        mockMvc.perform(get("/api/announcements"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].title").value("live"))
                .andExpect(jsonPath("$[0].published").value(true));

        verify(service).listPublished();
    }

    @Test
    void listIncludesDraftsWhenPublishedOnlyIsFalse() throws Exception {
        when(service.listAll())
                .thenReturn(
                        Arrays.asList(
                                new Announcement("live", "body", true),
                                new Announcement("draft", "body", false)));

        mockMvc.perform(get("/api/announcements").param("publishedOnly", "false"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[1].title").value("draft"))
                .andExpect(jsonPath("$[1].published").value(false));

        verify(service).listAll();
    }

    @Test
    void getByIdReturnsTheAnnouncement() throws Exception {
        when(service.get(7L)).thenReturn(new Announcement("release", "v1 is out", true));

        mockMvc.perform(get("/api/announcements/7"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("release"))
                .andExpect(jsonPath("$.body").value("v1 is out"))
                .andExpect(jsonPath("$.createdAt").exists());
    }

    @Test
    void unknownIdIsTranslatedToNotFound() throws Exception {
        when(service.get(404L)).thenThrow(new NoSuchElementException("announcement 404 not found"));

        mockMvc.perform(get("/api/announcements/404"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("Not Found"))
                .andExpect(jsonPath("$.message").value("announcement 404 not found"));
    }

    @Test
    void publishReturnsThePublishedAnnouncement() throws Exception {
        when(service.publish(3L)).thenReturn(new Announcement("draft", "body", true));

        mockMvc.perform(post("/api/announcements/3/publish"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.published").value(true));

        verify(service).publish(3L);
    }

    @Test
    void createRejectsBlankTitle() throws Exception {
        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"title\":\"\",\"body\":\"body\",\"published\":true}"))
                .andExpect(status().isBadRequest());
    }
}
