package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

import com.otterworks.legacyportal.announcements.AnnouncementController.AnnouncementResponse;
import com.otterworks.legacyportal.announcements.AnnouncementController.CreateAnnouncementRequest;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class AnnouncementControllerTest {

    @Mock private AnnouncementService service;

    @InjectMocks private AnnouncementController controller;

    @Test
    void listDefaultsToPublishedOnly() {
        when(service.listPublished())
                .thenReturn(Collections.singletonList(new Announcement("live", "body", true)));

        List<AnnouncementResponse> responses = controller.list(true);

        assertThat(responses).extracting(AnnouncementResponse::getTitle).containsExactly("live");
        verify(service).listPublished();
        verifyNoMoreInteractions(service);
    }

    @Test
    void listWithPublishedOnlyFalseIncludesDrafts() {
        when(service.listAll())
                .thenReturn(
                        Arrays.asList(
                                new Announcement("live", "body", true),
                                new Announcement("draft", "body", false)));

        List<AnnouncementResponse> responses = controller.list(false);

        assertThat(responses)
                .extracting(AnnouncementResponse::getTitle)
                .containsExactly("live", "draft");
        assertThat(responses).extracting(AnnouncementResponse::isPublished).containsExactly(true, false);
        verify(service).listAll();
        verifyNoMoreInteractions(service);
    }

    @Test
    void getMapsTheEntityOntoTheResponse() {
        Announcement announcement = new Announcement("Release", "v1 is out", true);
        when(service.get(7L)).thenReturn(announcement);

        AnnouncementResponse response = controller.get(7L);

        assertThat(response.getTitle()).isEqualTo("Release");
        assertThat(response.getBody()).isEqualTo("v1 is out");
        assertThat(response.isPublished()).isTrue();
        assertThat(response.getCreatedAt()).isEqualTo(announcement.getCreatedAt());
    }

    @Test
    void createForwardsRequestFieldsToTheService() {
        CreateAnnouncementRequest request = new CreateAnnouncementRequest();
        request.setTitle("Maintenance");
        request.setBody("Sunday 02:00 UTC");
        request.setPublished(false);
        when(service.create("Maintenance", "Sunday 02:00 UTC", false))
                .thenReturn(new Announcement("Maintenance", "Sunday 02:00 UTC", false));

        AnnouncementResponse response = controller.create(request);

        assertThat(request.getTitle()).isEqualTo("Maintenance");
        assertThat(request.getBody()).isEqualTo("Sunday 02:00 UTC");
        assertThat(request.isPublished()).isFalse();
        assertThat(response.getTitle()).isEqualTo("Maintenance");
        assertThat(response.isPublished()).isFalse();
    }

    @Test
    void publishReturnsThePublishedAnnouncement() {
        Announcement published = new Announcement("draft", "body", false);
        published.setPublished(true);
        when(service.publish(3L)).thenReturn(published);

        AnnouncementResponse response = controller.publish(3L);

        assertThat(response.isPublished()).isTrue();
        verify(service).publish(3L);
    }
}
