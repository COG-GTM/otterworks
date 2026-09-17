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

@ExtendWith(MockitoExtension.class)
class FeedbackServiceRatingRulesTest {

    @Mock private FeedbackRepository repository;
    @InjectMocks private FeedbackService service;

    @ParameterizedTest
    @ValueSource(ints = {Integer.MIN_VALUE, -1, 0, 6, 100, Integer.MAX_VALUE})
    void ratingsOutsideOneToFiveAreRejected(int rating) {
        assertThatThrownBy(() -> service.submit("u1", rating, "message"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("rating must be between 1 and 5");

        verify(repository, never()).save(any());
    }

    @ParameterizedTest
    @ValueSource(ints = {1, 2, 3, 4, 5})
    void ratingsInsideOneToFiveArePersisted(int rating) {
        when(repository.save(any(Feedback.class))).thenAnswer(i -> i.getArgument(0));

        Feedback saved = service.submit("u1", rating, "message");

        assertThat(saved.getRating()).isEqualTo(rating);
        assertThat(saved.getUserId()).isEqualTo("u1");
        assertThat(saved.getMessage()).isEqualTo("message");
        verify(repository).save(any(Feedback.class));
    }

    @Test
    void averageRatingIsZeroWhenThereIsNoFeedback() {
        when(repository.findAll()).thenReturn(Collections.emptyList());

        assertThat(service.averageRating()).isZero();
    }

    @Test
    void averageRatingIsTheMeanOfEveryStoredRating() {
        when(repository.findAll())
                .thenReturn(
                        Arrays.asList(
                                new Feedback("u1", 1, "a"),
                                new Feedback("u2", 2, "b"),
                                new Feedback("u3", 4, "c")));

        assertThat(service.averageRating()).isEqualTo(7.0 / 3.0);
    }

    @Test
    void listForUserDelegatesToTheOrderedRepositoryQuery() {
        Feedback entry = new Feedback("u1", 5, "great");
        when(repository.findByUserIdOrderByCreatedAtDesc("u1"))
                .thenReturn(Collections.singletonList(entry));

        assertThat(service.listForUser("u1")).containsExactly(entry);
    }
}
