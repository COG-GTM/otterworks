package com.otterworks.legacyportal.feedback;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.autoconfigure.orm.jpa.TestEntityManager;
import org.springframework.test.util.ReflectionTestUtils;

@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
class FeedbackRepositoryTest {

    @Autowired private FeedbackRepository repository;
    @Autowired private TestEntityManager entityManager;

    /** Pins {@code createdAt} so ordering does not depend on the platform clock resolution. */
    private static Feedback dated(String userId, int rating, String message, String createdAt) {
        Feedback feedback = new Feedback(userId, rating, message);
        ReflectionTestUtils.setField(feedback, "createdAt", Instant.parse(createdAt));
        return feedback;
    }

    @Test
    void everyFieldSurvivesAReloadFromTheDatabase() {
        Instant before = Instant.now();
        Long id = entityManager.persistAndGetId(new Feedback("slice-u3", 4, "useful"), Long.class);
        entityManager.flush();
        entityManager.clear();

        Feedback reloaded = repository.findById(id).orElseThrow(AssertionError::new);

        assertThat(reloaded.getId()).isEqualTo(id);
        assertThat(reloaded.getUserId()).isEqualTo("slice-u3");
        assertThat(reloaded.getRating()).isEqualTo(4);
        assertThat(reloaded.getMessage()).isEqualTo("useful");
        assertThat(reloaded.getCreatedAt()).isAfterOrEqualTo(before.minusSeconds(1));
    }

    @Test
    void findByUserIdReturnsNewestFirstAndIgnoresOtherUsers() {
        entityManager.persist(dated("slice-u1", 1, "oldest", "2024-01-01T00:00:00Z"));
        entityManager.persist(dated("slice-u1", 5, "newest", "2024-06-01T00:00:00Z"));
        entityManager.persist(dated("slice-u2", 3, "someone else", "2024-12-01T00:00:00Z"));
        entityManager.flush();
        entityManager.clear();

        List<Feedback> forUser = repository.findByUserIdOrderByCreatedAtDesc("slice-u1");

        assertThat(forUser).extracting(Feedback::getMessage).containsExactly("newest", "oldest");
    }

    @Test
    void findByUserIdIsEmptyForAnUnknownUser() {
        assertThat(repository.findByUserIdOrderByCreatedAtDesc("nobody")).isEmpty();
    }
}
