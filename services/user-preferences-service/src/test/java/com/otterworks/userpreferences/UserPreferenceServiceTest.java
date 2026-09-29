package com.otterworks.userpreferences;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;

@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import(UserPreferenceService.class)
class UserPreferenceServiceTest {

    @Autowired private UserPreferenceService service;

    @Test
    void unknownUserGetsDefaults() {
        UserPreference prefs = service.getOrDefault("nobody");

        assertThat(prefs.getTheme()).isEqualTo(UserPreferenceService.DEFAULT_THEME);
        assertThat(prefs.getLocale()).isEqualTo(UserPreferenceService.DEFAULT_LOCALE);
        assertThat(prefs.isEmailNotifications()).isTrue();
    }

    @Test
    void savePersistsAndUpdates() {
        service.save("u1", "dark", "fr-FR", false);

        UserPreference stored = service.getOrDefault("u1");
        assertThat(stored.getTheme()).isEqualTo("dark");
        assertThat(stored.getLocale()).isEqualTo("fr-FR");
        assertThat(stored.isEmailNotifications()).isFalse();

        service.save("u1", "light", "en-US", true);
        UserPreference updated = service.getOrDefault("u1");
        assertThat(updated.getTheme()).isEqualTo("light");
        assertThat(updated.isEmailNotifications()).isTrue();
    }
}
