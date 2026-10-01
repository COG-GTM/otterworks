package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Arrays;
import java.util.Collections;
import java.util.NoSuchElementException;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class AnnouncementServiceListAllTest {

    @Mock private AnnouncementRepository repository;
    @InjectMocks private AnnouncementService service;

    @Test
    void listAllIncludesDraftsAndPublishedAlike() {
        Announcement draft = new Announcement("draft", "body", false);
        Announcement live = new Announcement("live", "body", true);
        when(repository.findAll()).thenReturn(Arrays.asList(draft, live));

        assertThat(service.listAll()).containsExactly(draft, live);
    }

    @Test
    void listAllIsEmptyWhenNothingIsStored() {
        when(repository.findAll()).thenReturn(Collections.emptyList());

        assertThat(service.listAll()).isEmpty();
    }

    @Test
    void createStoresTheSuppliedFields() {
        when(repository.save(any(Announcement.class))).thenAnswer(i -> i.getArgument(0));

        Announcement created = service.create("title", "body", true);

        assertThat(created.getTitle()).isEqualTo("title");
        assertThat(created.getBody()).isEqualTo("body");
        assertThat(created.isPublished()).isTrue();
    }

    @Test
    void publishOfAMissingAnnouncementDoesNotSave() {
        when(repository.findById(5L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.publish(5L))
                .isInstanceOf(NoSuchElementException.class)
                .hasMessage("announcement 5 not found");

        verify(repository, never()).save(any());
    }
}
