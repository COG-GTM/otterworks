package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import org.junit.jupiter.api.Test;

class AnnouncementTest {

    @Test
    void constructorSetsFieldsAndCreatedAt() {
        Instant before = Instant.now();
        Announcement a = new Announcement("t", "b", false);

        assertThat(a.getId()).isNull();
        assertThat(a.getTitle()).isEqualTo("t");
        assertThat(a.getBody()).isEqualTo("b");
        assertThat(a.isPublished()).isFalse();
        assertThat(a.getCreatedAt()).isBetween(before, Instant.now());
    }

    @Test
    void settersUpdateMutableFields() {
        Announcement a = new Announcement("t", "b", false);

        a.setTitle("t2");
        a.setBody("b2");
        a.setPublished(true);

        assertThat(a.getTitle()).isEqualTo("t2");
        assertThat(a.getBody()).isEqualTo("b2");
        assertThat(a.isPublished()).isTrue();
    }
}
