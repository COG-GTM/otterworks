package com.otterworks.legacyportal.announcements;

import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.time.Instant;
import java.util.Arrays;
import java.util.Collections;
import java.util.NoSuchElementException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;

/** Web-layer tests for the announcements module: the service is mocked at the boundary. */
@WebMvcTest(AnnouncementController.class)
class AnnouncementControllerTest {

    private static final Instant CREATED_AT = Instant.parse("2024-03-04T05:06:07Z");

    @Autowired private MockMvc mockMvc;

    @MockBean private AnnouncementService service;

    private static Announcement announcement(long id, String title, boolean published) {
        Announcement announcement = new Announcement(title, "body of " + title, published);
        ReflectionTestUtils.setField(announcement, "id", id);
        ReflectionTestUtils.setField(announcement, "createdAt", CREATED_AT);
        return announcement;
    }

    @Test
    void listDefaultsToPublishedOnly() throws Exception {
        when(service.listPublished())
                .thenReturn(Collections.singletonList(announcement(1L, "live", true)));

        mockMvc.perform(get("/api/announcements"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].id").value(1))
                .andExpect(jsonPath("$[0].title").value("live"))
                .andExpect(jsonPath("$[0].body").value("body of live"))
                .andExpect(jsonPath("$[0].published").value(true))
                .andExpect(jsonPath("$[0].createdAt").value("2024-03-04T05:06:07Z"));

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
    void getReturnsTheRequestedAnnouncement() throws Exception {
        when(service.get(42L)).thenReturn(announcement(42L, "release", true));

        mockMvc.perform(get("/api/announcements/42"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(42))
                .andExpect(jsonPath("$.title").value("release"));

        verify(service).get(42L);
    }

    @Test
    void getUnknownIdIsTranslatedToA404Problem() throws Exception {
        when(service.get(999L)).thenThrow(new NoSuchElementException("announcement 999 not found"));

        mockMvc.perform(get("/api/announcements/999"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("Not Found"))
                .andExpect(jsonPath("$.message").value("announcement 999 not found"));
    }

    @Test
    void createReturns201AndPassesTheRequestThrough() throws Exception {
        when(service.create("Release", "v1 is out", true))
                .thenReturn(announcement(5L, "Release", true));

        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(
                                        "{\"title\":\"Release\",\"body\":\"v1 is out\",\"published\":true}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").value(5))
                .andExpect(jsonPath("$.published").value(true));

        verify(service).create("Release", "v1 is out", true);
    }

    @Test
    void createDefaultsPublishedToFalseWhenOmitted() throws Exception {
        when(service.create("Draft", "wip", false)).thenReturn(announcement(6L, "Draft", false));

        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"title\":\"Draft\",\"body\":\"wip\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.published").value(false));

        verify(service).create("Draft", "wip", false);
    }

    @ParameterizedTest
    @ValueSource(
            strings = {
                "{\"title\":\"\",\"body\":\"no title\"}",
                "{\"title\":\"no body\",\"body\":\"  \"}",
                "{\"body\":\"title missing entirely\"}"
            })
    void invalidPayloadsAreRejectedBeforeReachingTheService(String payload) throws Exception {
        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content(payload))
                .andExpect(status().isBadRequest());

        verify(service, never()).create(anyString(), anyString(), anyBoolean());
    }

    @Test
    void tooLongTitleIsRejected() throws Exception {
        String title = new String(new char[201]).replace('\0', 'x');

        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"title\":\"" + title + "\",\"body\":\"b\"}"))
                .andExpect(status().isBadRequest());

        verifyNoInteractions(service);
    }

    @Test
    void publishFlipsTheAnnouncementToPublished() throws Exception {
        when(service.publish(8L)).thenReturn(announcement(8L, "now live", true));

        mockMvc.perform(post("/api/announcements/8/publish"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(8))
                .andExpect(jsonPath("$.published").value(true));

        verify(service).publish(8L);
    }
}
