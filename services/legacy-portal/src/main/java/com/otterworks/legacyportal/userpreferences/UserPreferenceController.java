package com.otterworks.legacyportal.userpreferences;

import com.otterworks.legacyportal.security.CurrentUser;
import javax.validation.Valid;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Size;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;
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

    @GetMapping("/me")
    public PreferenceResponse getMine(Authentication authentication) {
        return PreferenceResponse.from(service.getOrDefault(CurrentUser.id(authentication)));
    }

    @PutMapping("/me")
    public PreferenceResponse updateMine(
            Authentication authentication, @Valid @RequestBody UpdatePreferenceRequest request) {
        return save(CurrentUser.id(authentication), request);
    }

    @GetMapping("/{userId}")
    public PreferenceResponse get(@PathVariable String userId, Authentication authentication) {
        return PreferenceResponse.from(service.getOrDefault(requireSelf(userId, authentication)));
    }

    @PutMapping("/{userId}")
    public PreferenceResponse update(
            @PathVariable String userId,
            Authentication authentication,
            @Valid @RequestBody UpdatePreferenceRequest request) {
        return save(requireSelf(userId, authentication), request);
    }

    private PreferenceResponse save(String userId, UpdatePreferenceRequest request) {
        return PreferenceResponse.from(
                service.save(
                        userId,
                        request.getTheme(),
                        request.getLocale(),
                        request.isEmailNotifications()));
    }

    private static String requireSelf(String userId, Authentication authentication) {
        String caller = CurrentUser.id(authentication);
        if (!caller.equals(userId)) {
            throw new AccessDeniedException("preferences belong to another user");
        }
        return caller;
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
