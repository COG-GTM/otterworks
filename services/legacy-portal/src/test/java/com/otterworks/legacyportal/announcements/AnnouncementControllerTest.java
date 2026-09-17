package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
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
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(AnnouncementController.class)
class AnnouncementControllerTest {

    @Autowired private MockMvc mockMvc;

    @MockBean private AnnouncementService service;

    private static Announcement announcement(long id, String title, boolean published) {
        Announcement announcement = new Announcement(title, "body of " + title, published);
        ReflectionTestUtils.setField(announcement, "id", id);
        return announcement;
    }

    @Test
    void listDefaultsToPublishedOnly() throws Exception {
        when(service.listPublished()).thenReturn(Collections.singletonList(announcement(1L, "live", true)));

        mockMvc.perform(get("/api/announcements"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].title").value("live"))
                .andExpect(jsonPath("$[0].published").value(true));

        verify(service).listPublished();
        verify(service, never()).listAll();
    }

    @Test
    void listWithPublishedOnlyFalseIncludesDrafts() throws Exception {
        when(service.listAll())
                .thenReturn(
                        Arrays.asList(announcement(1L, "live", true), announcement(2L, "draft", false)));

        mockMvc.perform(get("/api/announcements").param("publishedOnly", "false"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[1].title").value("draft"))
                .andExpect(jsonPath("$[1].published").value(false));

        verify(service).listAll();
        verify(service, never()).listPublished();
    }

    @Test
    void getByIdReturnsTheAnnouncement() throws Exception {
        when(service.get(3L)).thenReturn(announcement(3L, "notice", true));

        mockMvc.perform(get("/api/announcements/3"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(3))
                .andExpect(jsonPath("$.title").value("notice"))
                .andExpect(jsonPath("$.body").value("body of notice"))
                .andExpect(jsonPath("$.createdAt").isNotEmpty());
    }

    @Test
    void unknownAnnouncementIsTranslatedToNotFoundBody() throws Exception {
        when(service.get(404L)).thenThrow(new NoSuchElementException("announcement 404 not found"));

        mockMvc.perform(get("/api/announcements/404"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("Not Found"))
                .andExpect(jsonPath("$.message").value("announcement 404 not found"));
    }

    @Test
    void createReturnsCreatedWithTheStoredAnnouncement() throws Exception {
        when(service.create("notice", "please read", true))
                .thenReturn(announcement(5L, "notice", true));

        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"title\":\"notice\",\"body\":\"please read\","
                                                + "\"published\":true}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(5))
                .andExpect(jsonPath("$.published").value(true));

        verify(service).create("notice", "please read", true);
    }

    @Test
    void createRejectsABlankTitle() throws Exception {
        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"title\":\"  \",\"body\":\"text\",\"published\":true}"))
                .andExpect(status().isBadRequest());

        verify(service, never()).create(anyString(), anyString(), anyBoolean());
    }

    @Test
    void publishEndpointFlipsTheFlag() throws Exception {
        when(service.publish(9L)).thenReturn(announcement(9L, "draft", true));

        mockMvc.perform(post("/api/announcements/9/publish"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(9))
                .andExpect(jsonPath("$.published").value(true));

        verify(service).publish(9L);
    }

    @Test
    void publishingAnUnknownAnnouncementIsNotFound() throws Exception {
        when(service.publish(77L)).thenThrow(new NoSuchElementException("announcement 77 not found"));

        mockMvc.perform(post("/api/announcements/77/publish"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.message").value("announcement 77 not found"));
    }

    @Test
    void requestPayloadAccessorsRoundTrip() {
        AnnouncementController.CreateAnnouncementRequest request =
                new AnnouncementController.CreateAnnouncementRequest();
        request.setTitle("t");
        request.setBody("b");
        request.setPublished(true);

        assertThat(request.getTitle()).isEqualTo("t");
        assertThat(request.getBody()).isEqualTo("b");
        assertThat(request.isPublished()).isTrue();
    }
}
