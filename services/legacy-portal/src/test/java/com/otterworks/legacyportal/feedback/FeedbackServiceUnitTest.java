package com.otterworks.legacyportal.feedback;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Arrays;
import java.util.Collections;
import org.junit.jupiter.api.Test;

class FeedbackServiceUnitTest {

    private final FeedbackRepository repository = mock(FeedbackRepository.class);
    private final FeedbackService service = new FeedbackService(repository);

    @Test
    void averageRatingIsZeroWhenThereIsNoFeedback() {
        when(repository.findAll()).thenReturn(Collections.emptyList());

        assertThat(service.averageRating()).isEqualTo(0.0);
    }

    @Test
    void averageRatingIsMeanOfAllRatings() {
        when(repository.findAll())
                .thenReturn(
                        Arrays.asList(
                                new Feedback("a", 1, "x"),
                                new Feedback("b", 2, "y"),
                                new Feedback("c", 5, "z")));

        assertThat(service.averageRating()).isEqualTo(8.0 / 3.0);
    }

    @Test
    void boundaryRatingsAreAccepted() {
        when(repository.save(any(Feedback.class))).thenAnswer(inv -> inv.getArgument(0));

        assertThat(service.submit("u", FeedbackService.MIN_RATING, "low").getRating()).isEqualTo(1);
        assertThat(service.submit("u", FeedbackService.MAX_RATING, "high").getRating()).isEqualTo(5);
    }

    @Test
    void outOfRangeRatingIsNotPersisted() {
        assertThatThrownBy(() -> service.submit("u", 6, "x"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("rating must be between 1 and 5");
        verify(repository, never()).save(any());
    }
}
