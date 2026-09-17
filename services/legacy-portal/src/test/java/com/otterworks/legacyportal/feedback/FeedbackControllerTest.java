package com.otterworks.legacyportal.feedback;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.otterworks.legacyportal.feedback.FeedbackController.AverageRatingResponse;
import com.otterworks.legacyportal.feedback.FeedbackController.FeedbackResponse;
import com.otterworks.legacyportal.feedback.FeedbackController.SubmitFeedbackRequest;
import java.util.Arrays;
import java.util.List;
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
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class FeedbackControllerTest {

    private static ValidatorFactory validatorFactory;
    private static Validator validator;

    @Mock private FeedbackService service;

    @InjectMocks private FeedbackController controller;

    @BeforeAll
    static void openValidator() {
        validatorFactory = Validation.buildDefaultValidatorFactory();
        validator = validatorFactory.getValidator();
    }

    @AfterAll
    static void closeValidator() {
        validatorFactory.close();
    }

    private static SubmitFeedbackRequest request(String userId, int rating, String message) {
        SubmitFeedbackRequest request = new SubmitFeedbackRequest();
        request.setUserId(userId);
        request.setRating(rating);
        request.setMessage(message);
        return request;
    }

    @Test
    void submitForwardsRequestFieldsAndMapsTheSavedEntity() {
        SubmitFeedbackRequest request = request("u1", 5, "great");
        Feedback saved = new Feedback("u1", 5, "great");
        when(service.submit("u1", 5, "great")).thenReturn(saved);

        FeedbackResponse response = controller.submit(request);

        assertThat(request.getUserId()).isEqualTo("u1");
        assertThat(request.getRating()).isEqualTo(5);
        assertThat(request.getMessage()).isEqualTo("great");
        assertThat(response.getId()).isNull();
        assertThat(response.getUserId()).isEqualTo("u1");
        assertThat(response.getRating()).isEqualTo(5);
        assertThat(response.getMessage()).isEqualTo("great");
        assertThat(response.getCreatedAt()).isEqualTo(saved.getCreatedAt());
    }

    @Test
    void listForUserMapsEveryEntryInOrder() {
        when(service.listForUser("u1"))
                .thenReturn(Arrays.asList(new Feedback("u1", 5, "great"), new Feedback("u1", 3, "ok")));

        List<FeedbackResponse> responses = controller.listForUser("u1");

        assertThat(responses).extracting(FeedbackResponse::getMessage).containsExactly("great", "ok");
        assertThat(responses).extracting(FeedbackResponse::getRating).containsExactly(5, 3);
        verify(service).listForUser("u1");
    }

    @Test
    void listForUserReturnsAnEmptyListForAnUnknownUser() {
        when(service.listForUser("nobody")).thenReturn(java.util.Collections.emptyList());

        assertThat(controller.listForUser("nobody")).isEmpty();
    }

    @Test
    void averageRatingIsPassedThroughUnrounded() {
        when(service.averageRating()).thenReturn(3.5);

        AverageRatingResponse response = controller.averageRating();

        assertThat(response.getAverageRating()).isEqualTo(3.5);
    }

    @ParameterizedTest
    @ValueSource(ints = {0, -1, 6, 100})
    void ratingsOutsideOneToFiveAreRejectedByValidation(int rating) {
        Set<ConstraintViolation<SubmitFeedbackRequest>> violations =
                validator.validate(request("u1", rating, "message"));

        assertThat(violations).extracting(v -> v.getPropertyPath().toString()).containsExactly("rating");
    }

    @ParameterizedTest
    @ValueSource(ints = {1, 3, 5})
    void ratingsInsideOneToFiveAreAccepted(int rating) {
        assertThat(validator.validate(request("u1", rating, "message"))).isEmpty();
    }

    @ParameterizedTest
    @CsvSource(
            value = {
                ",message,userId",
                "'   ',message,userId",
                "u1,,message",
                "u1,'   ',message"
            })
    void blankUserIdOrMessageIsRejected(String userId, String message, String expectedField) {
        Set<ConstraintViolation<SubmitFeedbackRequest>> violations =
                validator.validate(request(userId, 3, message));

        assertThat(violations.stream().map(v -> v.getPropertyPath().toString()).collect(Collectors.toSet()))
                .containsExactly(expectedField);
    }

    @Test
    void oversizedUserIdAndMessageAreRejected() {
        String longUserId = repeat("u", 101);
        String longMessage = repeat("m", 2001);

        Set<ConstraintViolation<SubmitFeedbackRequest>> violations =
                validator.validate(request(longUserId, 3, longMessage));

        assertThat(violations.stream().map(v -> v.getPropertyPath().toString()).collect(Collectors.toSet()))
                .containsExactlyInAnyOrder("userId", "message");
        assertThat(validator.validate(request(repeat("u", 100), 3, repeat("m", 2000)))).isEmpty();
    }

    private static String repeat(String unit, int times) {
        StringBuilder builder = new StringBuilder(unit.length() * times);
        for (int i = 0; i < times; i++) {
            builder.append(unit);
        }
        return builder.toString();
    }
}
