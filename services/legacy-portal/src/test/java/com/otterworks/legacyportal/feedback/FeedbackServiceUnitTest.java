package com.otterworks.legacyportal.feedback;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Arrays;
import java.util.Collections;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/** Repository-mocked tests for the paths the {@code @DataJpaTest} suite does not exercise. */
@ExtendWith(MockitoExtension.class)
class FeedbackServiceUnitTest {

    @Mock private FeedbackRepository repository;

    @InjectMocks private FeedbackService service;

    @Test
    void averageRatingIsZeroWhenThereIsNoFeedbackAtAll() {
        when(repository.findAll()).thenReturn(Collections.emptyList());

        assertThat(service.averageRating()).isEqualTo(0.0);
    }

    @Test
    void averageRatingIsTheMeanOfEveryStoredRating() {
        when(repository.findAll())
                .thenReturn(
                        Arrays.asList(
                                new Feedback("u1", 5, "a"),
                                new Feedback("u2", 2, "b"),
                                new Feedback("u3", 2, "c")));

        assertThat(service.averageRating()).isEqualTo(3.0);
    }

    @ParameterizedTest
    @ValueSource(ints = {FeedbackService.MIN_RATING, 3, FeedbackService.MAX_RATING})
    void ratingsInsideTheAllowedRangeArePersisted(int rating) {
        when(repository.save(any(Feedback.class))).thenAnswer(i -> i.getArgument(0));

        Feedback saved = service.submit("u1", rating, "message");

        assertThat(saved.getRating()).isEqualTo(rating);
        assertThat(saved.getUserId()).isEqualTo("u1");
        assertThat(saved.getMessage()).isEqualTo("message");
        assertThat(saved.getCreatedAt()).isNotNull();
    }

    @ParameterizedTest
    @ValueSource(ints = {Integer.MIN_VALUE, -1, 0, 6, Integer.MAX_VALUE})
    void ratingsOutsideTheAllowedRangeAreRejectedWithoutTouchingTheRepository(int rating) {
        assertThatThrownBy(() -> service.submit("u1", rating, "message"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("rating must be between 1 and 5");

        verify(repository, never()).save(any());
    }

    @Test
    void listForUserDelegatesToTheNewestFirstFinder() {
        Feedback newest = new Feedback("u1", 4, "newest");
        when(repository.findByUserIdOrderByCreatedAtDesc("u1"))
                .thenReturn(Collections.singletonList(newest));

        assertThat(service.listForUser("u1")).containsExactly(newest);
    }
}
