package com.otterworks.legacyportal.userpreferences;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.otterworks.legacyportal.userpreferences.UserPreferenceController.PreferenceResponse;
import com.otterworks.legacyportal.userpreferences.UserPreferenceController.UpdatePreferenceRequest;
import java.util.Set;
import java.util.stream.Collectors;
import javax.validation.ConstraintViolation;
import javax.validation.Validation;
import javax.validation.Validator;
import javax.validation.ValidatorFactory;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class UserPreferenceControllerTest {

    private static ValidatorFactory validatorFactory;
    private static Validator validator;

    @Mock private UserPreferenceService service;

    @InjectMocks private UserPreferenceController controller;

    @BeforeAll
    static void openValidator() {
        validatorFactory = Validation.buildDefaultValidatorFactory();
        validator = validatorFactory.getValidator();
    }

    @AfterAll
    static void closeValidator() {
        validatorFactory.close();
    }

    private static UpdatePreferenceRequest request(
            String theme, String locale, boolean emailNotifications) {
        UpdatePreferenceRequest request = new UpdatePreferenceRequest();
        request.setTheme(theme);
        request.setLocale(locale);
        request.setEmailNotifications(emailNotifications);
        return request;
    }

    @Test
    void getMapsTheServiceResultOntoTheResponse() {
        when(service.getOrDefault("u1")).thenReturn(new UserPreference("u1", "dark", "fr-FR", false));

        PreferenceResponse response = controller.get("u1");

        assertThat(response.getUserId()).isEqualTo("u1");
        assertThat(response.getTheme()).isEqualTo("dark");
        assertThat(response.getLocale()).isEqualTo("fr-FR");
        assertThat(response.isEmailNotifications()).isFalse();
    }

    @Test
    void updateForwardsEveryRequestFieldToTheService() {
        UpdatePreferenceRequest request = request("dark", "fr-FR", true);
        when(service.save("u1", "dark", "fr-FR", true))
                .thenReturn(new UserPreference("u1", "dark", "fr-FR", true));

        PreferenceResponse response = controller.update("u1", request);

        assertThat(request.getTheme()).isEqualTo("dark");
        assertThat(request.getLocale()).isEqualTo("fr-FR");
        assertThat(request.isEmailNotifications()).isTrue();
        assertThat(response.getUserId()).isEqualTo("u1");
        assertThat(response.getTheme()).isEqualTo("dark");
        assertThat(response.getLocale()).isEqualTo("fr-FR");
        assertThat(response.isEmailNotifications()).isTrue();
        verify(service).save("u1", "dark", "fr-FR", true);
    }

    @Test
    void updateAcceptsAValidRequest() {
        assertThat(validator.validate(request("light", "en-US", false))).isEmpty();
    }

    @ParameterizedTest
    @CsvSource(
            value = {
                ",en-US,theme",
                "'   ',en-US,theme",
                "light,,locale",
                "light,'   ',locale"
            })
    void blankThemeOrLocaleIsRejected(String theme, String locale, String expectedField) {
        Set<ConstraintViolation<UpdatePreferenceRequest>> violations =
                validator.validate(request(theme, locale, true));

        assertThat(violations.stream().map(v -> v.getPropertyPath().toString()).collect(Collectors.toSet()))
                .containsExactly(expectedField);
    }

    @Test
    void themeAndLocaleLongerThanTwentyCharactersAreRejected() {
        String tooLong = "0123456789012345678901";

        Set<ConstraintViolation<UpdatePreferenceRequest>> violations =
                validator.validate(request(tooLong, tooLong, true));

        assertThat(violations.stream().map(v -> v.getPropertyPath().toString()).collect(Collectors.toSet()))
                .containsExactlyInAnyOrder("theme", "locale");
        assertThat(validator.validate(request("01234567890123456789", "01234567890123456789", true)))
                .isEmpty();
    }
}
