package com.otterworks.legacyportal.userpreferences;

import com.otterworks.legacyportal.security.UserIds;
import javax.validation.Valid;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Size;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/preferences")
public class UserPreferenceController {

    private final UserPreferenceService service;

    public UserPreferenceController(UserPreferenceService service) {
        this.service = service;
    }

    @GetMapping("/{userId}")
    public PreferenceResponse get(
            @PathVariable String userId, @AuthenticationPrincipal String principal) {
        requireOwner(userId, principal);
        return PreferenceResponse.from(service.getOrDefault(userId));
    }

    @PutMapping("/{userId}")
    public PreferenceResponse update(
            @PathVariable String userId,
            @AuthenticationPrincipal String principal,
            @Valid @RequestBody UpdatePreferenceRequest request) {
        requireOwner(userId, principal);
        return PreferenceResponse.from(
                service.save(
                        userId,
                        request.getTheme(),
                        request.getLocale(),
                        request.isEmailNotifications()));
    }

    /** Callers may only read or change their own preferences (path id == token subject). */
    private static void requireOwner(String userId, String principal) {
        UserIds.requireValid(userId);
        if (principal == null || !principal.equals(userId)) {
            throw new AccessDeniedException("Cannot access another user's preferences");
        }
    }

    public static class UpdatePreferenceRequest {

        @NotBlank
        @Size(max = 20)
        private String theme;

        @NotBlank
        @Size(max = 20)
        private String locale;

        private boolean emailNotifications;

        public String getTheme() {
            return theme;
        }

        public void setTheme(String theme) {
            this.theme = theme;
        }

        public String getLocale() {
            return locale;
        }

        public void setLocale(String locale) {
            this.locale = locale;
        }

        public boolean isEmailNotifications() {
            return emailNotifications;
        }

        public void setEmailNotifications(boolean emailNotifications) {
            this.emailNotifications = emailNotifications;
        }
    }

    public static class PreferenceResponse {

        private final String userId;
        private final String theme;
        private final String locale;
        private final boolean emailNotifications;

        private PreferenceResponse(
                String userId, String theme, String locale, boolean emailNotifications) {
            this.userId = userId;
            this.theme = theme;
            this.locale = locale;
            this.emailNotifications = emailNotifications;
        }

        static PreferenceResponse from(UserPreference p) {
            return new PreferenceResponse(
                    p.getUserId(), p.getTheme(), p.getLocale(), p.isEmailNotifications());
        }

        public String getUserId() {
            return userId;
        }

        public String getTheme() {
            return theme;
        }

        public String getLocale() {
            return locale;
        }

        public boolean isEmailNotifications() {
            return emailNotifications;
        }
    }
}
