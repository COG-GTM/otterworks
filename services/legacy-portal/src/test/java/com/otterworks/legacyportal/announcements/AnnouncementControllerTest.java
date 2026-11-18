package com.otterworks.legacyportal.announcements;

import static org.hamcrest.Matchers.hasItem;
import static org.hamcrest.Matchers.not;
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
class AnnouncementControllerTest {

    @Autowired private MockMvc mockMvc;
    @Autowired private AnnouncementService service;

    @Test
    void getReturnsAnnouncementById() throws Exception {
        Announcement saved = service.create("Maintenance", "Saturday 2am", true);

        mockMvc.perform(get("/api/announcements/{id}", saved.getId()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(saved.getId()))
                .andExpect(jsonPath("$.title").value("Maintenance"))
                .andExpect(jsonPath("$.body").value("Saturday 2am"))
                .andExpect(jsonPath("$.published").value(true))
                .andExpect(jsonPath("$.createdAt").exists());
    }

    @Test
    void getUnknownIdReturns404WithErrorBody() throws Exception {
        mockMvc.perform(get("/api/announcements/{id}", 987_654_321L))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("Not Found"))
                .andExpect(jsonPath("$.message").value("announcement 987654321 not found"));
    }

    @Test
    void publishFlipsDraftAndMakesItVisible() throws Exception {
        Announcement draft = service.create("Draft", "pending", false);

        mockMvc.perform(get("/api/announcements"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[*].id", not(hasItem(draft.getId().intValue()))));

        mockMvc.perform(post("/api/announcements/{id}/publish", draft.getId()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.published").value(true));

        mockMvc.perform(get("/api/announcements"))
                .andExpect(jsonPath("$[*].id", hasItem(draft.getId().intValue())));
    }

    @Test
    void publishUnknownIdReturns404() throws Exception {
        mockMvc.perform(post("/api/announcements/{id}/publish", 987_654_321L))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("Not Found"));
    }

    @Test
    void listWithPublishedOnlyFalseIncludesDrafts() throws Exception {
        Announcement draft = service.create("Hidden draft", "wip", false);

        mockMvc.perform(get("/api/announcements").param("publishedOnly", "false"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[*].id", hasItem(draft.getId().intValue())));
    }

    @Test
    void createRejectsBlankTitle() throws Exception {
        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"title\":\"  \",\"body\":\"text\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void createRejectsOverlongTitle() throws Exception {
        String title = "x".repeat(201);
        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"title\":\"" + title + "\",\"body\":\"text\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void createRejectsMalformedJson() throws Exception {
        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"title\":"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void createDefaultsToDraft() throws Exception {
        mockMvc.perform(
                        post("/api/announcements")
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"title\":\"No flag\",\"body\":\"text\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.published").value(false));
    }
}
