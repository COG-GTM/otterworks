package com.otterworks.legacyportal.feedback;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;

/** Boundary cases of {@link FeedbackService} that need a real (empty) repository. */
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import(FeedbackService.class)
class FeedbackAverageRatingTest {

    @Autowired private FeedbackService service;

    @Test
    void averageRatingIsZeroWhenNoFeedbackExists() {
        assertThat(service.averageRating()).isEqualTo(0.0);
    }

    @Test
    void averageRatingOfASingleEntryIsThatRating() {
        service.submit("u1", 2, "meh");

        assertThat(service.averageRating()).isEqualTo(2.0);
    }

    @Test
    void listForUserIsEmptyForAnUnknownUser() {
        service.submit("u1", 5, "great");

        assertThat(service.listForUser("someone-else")).isEmpty();
    }

    @Test
    void boundaryRatingsAreAccepted() {
        Feedback lowest = service.submit("u1", FeedbackService.MIN_RATING, "worst");
        Feedback highest = service.submit("u1", FeedbackService.MAX_RATING, "best");

        assertThat(lowest.getRating()).isEqualTo(1);
        assertThat(highest.getRating()).isEqualTo(5);
        assertThat(lowest.getUserId()).isEqualTo("u1");
        assertThat(lowest.getMessage()).isEqualTo("worst");
        assertThat(lowest.getCreatedAt()).isNotNull();
    }
}
