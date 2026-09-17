package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/** Repository-mocked tests for the paths the {@code @DataJpaTest} suite does not exercise. */
@ExtendWith(MockitoExtension.class)
class AnnouncementServiceUnitTest {

    @Mock private AnnouncementRepository repository;

    @InjectMocks private AnnouncementService service;

    @Test
    void listAllReturnsDraftsAndPublishedAnnouncementsUnfiltered() {
        Announcement draft = new Announcement("draft", "body", false);
        Announcement live = new Announcement("live", "body", true);
        when(repository.findAll()).thenReturn(Arrays.asList(draft, live));

        List<Announcement> all = service.listAll();

        assertThat(all).containsExactly(draft, live);
        verify(repository).findAll();
    }

    @Test
    void createStampsTheRequestedFieldsOntoANewAnnouncement() {
        when(repository.save(any(Announcement.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));

        Announcement created = service.create("title", "body", true);

        assertThat(created.getTitle()).isEqualTo("title");
        assertThat(created.getBody()).isEqualTo("body");
        assertThat(created.isPublished()).isTrue();
        assertThat(created.getCreatedAt()).isNotNull();
    }
}
