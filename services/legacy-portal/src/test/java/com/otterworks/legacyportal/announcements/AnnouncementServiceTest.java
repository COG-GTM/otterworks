package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import java.util.NoSuchElementException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;

@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import(AnnouncementService.class)
class AnnouncementServiceTest {

    @Autowired private AnnouncementService service;
    @Autowired private AnnouncementRepository repository;

    // QA-BILL-07: the embedded H2 database is shared across Spring contexts in one JVM, so rows
    // committed by full-context tests leak in here. Start from an empty table (rolled back).
    @BeforeEach
    void isolateFromOtherContexts() {
        repository.deleteAll();
    }

    @Test
    void listPublishedReturnsOnlyPublishedNewestFirst() {
        service.create("draft", "not visible", false);
        service.create("first", "hello", true);
        service.create("second", "world", true);

        List<Announcement> published = service.listPublished();

        assertThat(published).extracting(Announcement::getTitle).containsExactly("second", "first");
    }

    @Test
    void publishFlipsDraftToPublished() {
        Announcement draft = service.create("draft", "body", false);
        assertThat(draft.isPublished()).isFalse();

        Announcement published = service.publish(draft.getId());

        assertThat(published.isPublished()).isTrue();
        assertThat(service.listPublished()).extracting(Announcement::getId).contains(draft.getId());
    }

    @Test
    void getUnknownIdThrows() {
        assertThatThrownBy(() -> service.get(999_999L))
                .isInstanceOf(NoSuchElementException.class);
    }
}
