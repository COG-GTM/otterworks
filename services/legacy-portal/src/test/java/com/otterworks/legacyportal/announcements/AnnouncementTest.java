package com.otterworks.legacyportal.announcements;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class AnnouncementTest {

    @Test
    void constructorPopulatesEveryFieldAndStampsCreatedAt() {
        Announcement announcement = new Announcement("Release", "v1 is out", true);

        assertThat(announcement.getId()).isNull();
        assertThat(announcement.getTitle()).isEqualTo("Release");
        assertThat(announcement.getBody()).isEqualTo("v1 is out");
        assertThat(announcement.isPublished()).isTrue();
        assertThat(announcement.getCreatedAt()).isNotNull();
    }

    @Test
    void editingADraftReplacesTitleAndBodyButKeepsCreatedAt() {
        Announcement draft = new Announcement("typo", "wrong body", false);

        draft.setTitle("Release");
        draft.setBody("v1 is out");

        assertThat(draft.getTitle()).isEqualTo("Release");
        assertThat(draft.getBody()).isEqualTo("v1 is out");
        assertThat(draft.isPublished()).isFalse();
    }
}
