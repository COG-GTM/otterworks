package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class AnnouncementTest {

    @Test
    void constructorStoresTheSuppliedFieldsAndStampsCreationTime() {
        Announcement announcement = new Announcement("title", "body", true);

        assertThat(announcement.getId()).isNull();
        assertThat(announcement.getTitle()).isEqualTo("title");
        assertThat(announcement.getBody()).isEqualTo("body");
        assertThat(announcement.isPublished()).isTrue();
        assertThat(announcement.getCreatedAt()).isNotNull();
    }

    @Test
    void settersReplaceTheEditableFieldsWithoutTouchingCreationTime() {
        Announcement announcement = new Announcement("title", "body", false);

        announcement.setTitle("edited title");
        announcement.setBody("edited body");
        announcement.setPublished(true);

        assertThat(announcement.getTitle()).isEqualTo("edited title");
        assertThat(announcement.getBody()).isEqualTo("edited body");
        assertThat(announcement.isPublished()).isTrue();
        assertThat(announcement.getCreatedAt()).isNotNull();
    }
}
