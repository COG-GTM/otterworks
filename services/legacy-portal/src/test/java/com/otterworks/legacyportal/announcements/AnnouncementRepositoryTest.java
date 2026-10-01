package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.List;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.autoconfigure.orm.jpa.TestEntityManager;
import org.springframework.test.util.ReflectionTestUtils;

@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
class AnnouncementRepositoryTest {

    @Autowired private AnnouncementRepository repository;
    @Autowired private TestEntityManager entityManager;

    /**
     * The suite shares one named in-memory database, so ordering assertions look only at rows this
     * test created and pin their timestamps instead of relying on clock resolution.
     */
    private static Announcement dated(String title, boolean published, String createdAt) {
        Announcement announcement = new Announcement(title, "body", published);
        ReflectionTestUtils.setField(announcement, "createdAt", Instant.parse(createdAt));
        return announcement;
    }

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
        entityManager.persist(dated("slice-older", true, "2024-01-01T00:00:00Z"));
        entityManager.persist(dated("slice-newer", true, "2024-06-01T00:00:00Z"));
        entityManager.persist(dated("slice-draft", false, "2024-12-01T00:00:00Z"));
        entityManager.flush();
        entityManager.clear();

        List<String> titles =
                repository.findByPublishedTrueOrderByCreatedAtDesc().stream()
                        .map(Announcement::getTitle)
                        .collect(Collectors.toList());

        assertThat(titles).doesNotContain("slice-draft");
        assertThat(titles.stream().filter(t -> t.startsWith("slice-")).collect(Collectors.toList()))
                .containsExactly("slice-newer", "slice-older");
    }
}
