package com.otterworks.legacyportal.feedback;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.Collections;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

/** Repository-mocked counterpart to {@link FeedbackServiceTest}'s persistence slice. */
@ExtendWith(MockitoExtension.class)
class FeedbackServiceUnitTest {

    @Mock private FeedbackRepository repository;

    @InjectMocks private FeedbackService service;

    @Test
    void averageRatingIsZeroWhenNoFeedbackExists() {
        when(repository.findAll()).thenReturn(Collections.emptyList());

        assertThat(service.averageRating()).isEqualTo(0.0);
        verify(repository).findAll();
    }

    @Test
    void averageRatingOfASingleEntryIsThatRating() {
        when(repository.findAll()).thenReturn(Collections.singletonList(new Feedback("u1", 4, "a")));

        assertThat(service.averageRating()).isEqualTo(4.0);
    }
}
