package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/** Repository-mocked counterpart to {@link AnnouncementServiceTest}'s persistence slice. */
@ExtendWith(MockitoExtension.class)
class AnnouncementServiceUnitTest {

    @Mock private AnnouncementRepository repository;

    @InjectMocks private AnnouncementService service;

    @Test
    void listAllReturnsDraftsAndPublishedUnfiltered() {
        Announcement published = new Announcement("live", "body", true);
        Announcement draft = new Announcement("draft", "body", false);
        when(repository.findAll()).thenReturn(Arrays.asList(published, draft));

        List<Announcement> all = service.listAll();

        assertThat(all).containsExactly(published, draft);
        verify(repository).findAll();
    }
}
