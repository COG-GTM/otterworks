package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;

/** Persistence-level behaviour of the announcements module. */
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import(AnnouncementService.class)
class AnnouncementPersistenceTest {

    @Autowired private AnnouncementService service;

    @Autowired private AnnouncementRepository repository;

    @Test
    void listAllReturnsDraftsAndPublishedAlike() {
        service.create("draft", "not visible", false);
        service.create("live", "visible", true);

        assertThat(service.listAll())
                .extracting(Announcement::getTitle)
                .containsExactlyInAnyOrder("draft", "live");
        assertThat(service.listPublished()).hasSize(1);
    }

    @Test
    void listAllIsEmptyBeforeAnythingIsCreated() {
        assertThat(service.listAll()).isEmpty();
    }

    @Test
    void editingTitleAndBodyIsPersisted() {
        Announcement created = service.create("original", "original body", false);

        Announcement loaded = repository.findById(created.getId()).orElseThrow(AssertionError::new);
        loaded.setTitle("edited");
        loaded.setBody("edited body");
        repository.saveAndFlush(loaded);

        Announcement reloaded =
                repository.findById(created.getId()).orElseThrow(AssertionError::new);
        assertThat(reloaded.getTitle()).isEqualTo("edited");
        assertThat(reloaded.getBody()).isEqualTo("edited body");
        assertThat(reloaded.getCreatedAt()).isEqualTo(created.getCreatedAt());
        assertThat(reloaded.isPublished()).isFalse();
    }

    @Test
    void publishingAnAlreadyPublishedAnnouncementIsIdempotent() {
        Announcement published = service.create("live", "body", true);

        Announcement republished = service.publish(published.getId());

        assertThat(republished.isPublished()).isTrue();
        assertThat(service.listPublished()).hasSize(1);
    }
}
