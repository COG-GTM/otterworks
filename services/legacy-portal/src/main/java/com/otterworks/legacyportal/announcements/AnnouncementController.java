package com.otterworks.legacyportal.announcements;

import com.otterworks.legacyportal.security.PortalPrincipal;
import java.time.Instant;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.stream.Collectors;
import javax.validation.Valid;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Size;
import org.springframework.http.HttpStatus;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/announcements")
public class AnnouncementController {

    private final AnnouncementService service;

    public AnnouncementController(AnnouncementService service) {
        this.service = service;
    }

    @GetMapping
    public List<AnnouncementResponse> list(
            @AuthenticationPrincipal PortalPrincipal caller,
            @RequestParam(name = "publishedOnly", defaultValue = "true") boolean publishedOnly) {
        if (!publishedOnly && !caller.isAdmin()) {
            throw new AccessDeniedException("only admins can list unpublished announcements");
        }
        List<Announcement> announcements =
                publishedOnly ? service.listPublished() : service.listAll();
        return announcements.stream().map(AnnouncementResponse::from).collect(Collectors.toList());
    }

    @GetMapping("/{id}")
    public AnnouncementResponse get(
            @AuthenticationPrincipal PortalPrincipal caller, @PathVariable Long id) {
        Announcement announcement = service.get(id);
        if (!announcement.isPublished() && !caller.isAdmin()) {
            throw new NoSuchElementException("announcement " + id + " not found");
        }
        return AnnouncementResponse.from(announcement);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public AnnouncementResponse create(@Valid @RequestBody CreateAnnouncementRequest request) {
        return AnnouncementResponse.from(
                service.create(request.getTitle(), request.getBody(), request.isPublished()));
    }

    @PostMapping("/{id}/publish")
    public AnnouncementResponse publish(@PathVariable Long id) {
        return AnnouncementResponse.from(service.publish(id));
    }

    public static class CreateAnnouncementRequest {

        @NotBlank
        @Size(max = 200)
        private String title;

        @NotBlank
        @Size(max = 4000)
        private String body;

        private boolean published;

        public String getTitle() {
            return title;
        }

        public void setTitle(String title) {
            this.title = title;
        }

        public String getBody() {
            return body;
        }

        public void setBody(String body) {
            this.body = body;
        }

        public boolean isPublished() {
            return published;
        }

        public void setPublished(boolean published) {
            this.published = published;
        }
    }

    public static class AnnouncementResponse {

        private final Long id;
        private final String title;
        private final String body;
        private final boolean published;
        private final Instant createdAt;

        private AnnouncementResponse(
                Long id, String title, String body, boolean published, Instant createdAt) {
            this.id = id;
            this.title = title;
            this.body = body;
            this.published = published;
            this.createdAt = createdAt;
        }

        static AnnouncementResponse from(Announcement a) {
            return new AnnouncementResponse(
                    a.getId(), a.getTitle(), a.getBody(), a.isPublished(), a.getCreatedAt());
        }

        public Long getId() {
            return id;
        }

        public String getTitle() {
            return title;
        }

        public String getBody() {
            return body;
        }

        public boolean isPublished() {
            return published;
        }

        public Instant getCreatedAt() {
            return createdAt;
        }
    }
}
