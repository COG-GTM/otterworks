package com.otterworks.userpreferences;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class UserPreferenceService {

    static final String DEFAULT_THEME = "light";
    static final String DEFAULT_LOCALE = "en-US";

    private final UserPreferenceRepository repository;

    public UserPreferenceService(UserPreferenceRepository repository) {
        this.repository = repository;
    }

    /** Returns stored preferences, or sensible defaults if the user has none yet. */
    @Transactional(readOnly = true)
    public UserPreference getOrDefault(String userId) {
        return repository
                .findById(userId)
                .orElseGet(() -> new UserPreference(userId, DEFAULT_THEME, DEFAULT_LOCALE, true));
    }

    @Transactional
    public UserPreference save(String userId, String theme, String locale, boolean emailNotifications) {
        UserPreference preference =
                repository
                        .findById(userId)
                        .orElseGet(
                                () ->
                                        new UserPreference(
                                                userId, DEFAULT_THEME, DEFAULT_LOCALE, true));
        preference.setTheme(theme);
        preference.setLocale(locale);
        preference.setEmailNotifications(emailNotifications);
        return repository.save(preference);
    }
}
