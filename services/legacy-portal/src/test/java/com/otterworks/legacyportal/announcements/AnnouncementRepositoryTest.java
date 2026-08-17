package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.autoconfigure.orm.jpa.TestEntityManager;

@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
class AnnouncementRepositoryTest {

    @Autowired private AnnouncementRepository repository;
    @Autowired private TestEntityManager entityManager;

    @Test
    void everyFieldSurvivesAReloadFromTheDatabase() {
        Instant before = Instant.now();
        Long id =
                entityManager.persistAndGetId(
                        new Announcement("maintenance", "portal down at 9pm", true), Long.class);
        entityManager.flush();
        entityManager.clear();

        Announcement reloaded = repository.findById(id).orElseThrow(AssertionError::new);

        assertThat(reloaded.getId()).isEqualTo(id);
        assertThat(reloaded.getTitle()).isEqualTo("maintenance");
        assertThat(reloaded.getBody()).isEqualTo("portal down at 9pm");
        assertThat(reloaded.isPublished()).isTrue();
        assertThat(reloaded.getCreatedAt()).isAfterOrEqualTo(before.minusSeconds(1));
    }

    @Test
    void titleAndBodyEditsArePersisted() {
        Announcement stored =
                entityManager.persistFlushFind(new Announcement("old title", "old body", false));

        stored.setTitle("new title");
        stored.setBody("new body");
        entityManager.flush();
        entityManager.clear();

        Announcement reloaded =
                repository.findById(stored.getId()).orElseThrow(AssertionError::new);
        assertThat(reloaded.getTitle()).isEqualTo("new title");
        assertThat(reloaded.getBody()).isEqualTo("new body");
        assertThat(reloaded.isPublished()).isFalse();
    }

    @Test
    void findByPublishedTrueSkipsDraftsAndOrdersNewestFirst() {
        entityManager.persist(new Announcement("older", "body", true));
        entityManager.persist(new Announcement("newer", "body", true));
        entityManager.persist(new Announcement("draft", "body", false));
        entityManager.flush();
        entityManager.clear();

        List<Announcement> published = repository.findByPublishedTrueOrderByCreatedAtDesc();

        assertThat(published).extracting(Announcement::getTitle).containsExactly("newer", "older");
    }
}
