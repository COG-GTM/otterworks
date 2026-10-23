package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.hasItem;
import static org.hamcrest.Matchers.not;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.otterworks.legacyportal.security.TestTokens;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

@SpringBootTest(properties = "legacyportal.security.jwt-secret=" + TestTokens.SECRET)
@AutoConfigureMockMvc
class AnnouncementControllerTest {

    private static final String ADMIN = TestTokens.bearer("admin-1", "USER", "ADMIN");
    private static final String OWNER = TestTokens.bearer("owner-1", "OWNER");
    private static final String USER = TestTokens.bearer("user-1", "USER", "EDITOR");
    private static final String PAYLOAD =
            "{\"title\":\"Injected\",\"body\":\"<a href=//evil>login</a>\",\"published\":true}";

    @Autowired private MockMvc mockMvc;
    @Autowired private AnnouncementRepository repository;
    @Autowired private AnnouncementService service;

    @BeforeEach
    @AfterEach
    void clean() {
        repository.deleteAll();
    }

    private static MockHttpServletRequestBuilder create(String body) {
        return post("/api/announcements").contentType(MediaType.APPLICATION_JSON).content(body);
    }

    @Test
    void anonymousCannotCreate() throws Exception {
        mockMvc.perform(create(PAYLOAD)).andExpect(status().isUnauthorized());
        assertThat(repository.count()).isZero();
    }

    @Test
    void invalidOrForgedTokenCannotCreate() throws Exception {
        mockMvc.perform(create(PAYLOAD).header(HttpHeaders.AUTHORIZATION, "Bearer not-a-jwt"))
                .andExpect(status().isUnauthorized());
        String forged = ADMIN.substring(0, ADMIN.length() - 4) + "AAAA";
        mockMvc.perform(create(PAYLOAD).header(HttpHeaders.AUTHORIZATION, forged))
                .andExpect(status().isUnauthorized());
        assertThat(repository.count()).isZero();
    }

    @Test
    void nonAdminCannotCreate() throws Exception {
        mockMvc.perform(create(PAYLOAD).header(HttpHeaders.AUTHORIZATION, USER))
                .andExpect(status().isForbidden());
        assertThat(repository.count()).isZero();
    }

    @Test
    void adminAndOwnerCanCreate() throws Exception {
        mockMvc.perform(create(PAYLOAD).header(HttpHeaders.AUTHORIZATION, ADMIN))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.title").value("Injected"))
                .andExpect(jsonPath("$.published").value(true));
        mockMvc.perform(
                        create("{\"title\":\"Draft\",\"body\":\"b\"}")
                                .header(HttpHeaders.AUTHORIZATION, OWNER))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.published").value(false));
        assertThat(repository.count()).isEqualTo(2);
    }

    @Test
    void adminCreateStillValidates() throws Exception {
        mockMvc.perform(
                        create("{\"title\":\"\",\"body\":\"b\"}")
                                .header(HttpHeaders.AUTHORIZATION, ADMIN))
                .andExpect(status().isBadRequest());
    }

    @Test
    void onlyAdminsCanPublish() throws Exception {
        Long id = service.create("draft", "body", false).getId();
        String path = "/api/announcements/" + id + "/publish";

        mockMvc.perform(post(path)).andExpect(status().isUnauthorized());
        mockMvc.perform(post(path).header(HttpHeaders.AUTHORIZATION, USER))
                .andExpect(status().isForbidden());
        assertThat(service.get(id).isPublished()).isFalse();

        mockMvc.perform(post(path).header(HttpHeaders.AUTHORIZATION, ADMIN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.published").value(true));
        assertThat(service.get(id).isPublished()).isTrue();
    }

    @Test
    void publishedListStaysPublicAndHidesDrafts() throws Exception {
        service.create("draft", "secret", false);
        service.create("live", "hello", true);

        mockMvc.perform(get("/api/announcements"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[*].title", not(hasItem("draft"))));
    }

    @Test
    void draftListingRequiresAdmin() throws Exception {
        service.create("draft", "secret", false);
        service.create("live", "hello", true);

        mockMvc.perform(get("/api/announcements").param("publishedOnly", "false"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/announcements").param("publishedOnly", "no"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(
                        get("/api/announcements")
                                .param("publishedOnly", "false")
                                .header(HttpHeaders.AUTHORIZATION, USER))
                .andExpect(status().isForbidden());
        mockMvc.perform(
                        get("/api/announcements")
                                .param("publishedOnly", "false")
                                .header(HttpHeaders.AUTHORIZATION, ADMIN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[*].title", hasItem("draft")));
    }

    @Test
    void draftByIdIsHiddenFromNonAdmins() throws Exception {
        Long draft = service.create("draft", "secret", false).getId();
        Long live = service.create("live", "hello", true).getId();

        mockMvc.perform(get("/api/announcements/" + draft)).andExpect(status().isNotFound());
        mockMvc.perform(get("/api/announcements/" + draft).header(HttpHeaders.AUTHORIZATION, USER))
                .andExpect(status().isNotFound());
        mockMvc.perform(get("/api/announcements/" + draft).header(HttpHeaders.AUTHORIZATION, ADMIN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("draft"));
        mockMvc.perform(get("/api/announcements/" + live))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.title").value("live"));
    }
}
