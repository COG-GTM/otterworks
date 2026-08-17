package com.otterworks.legacyportal.feedback;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.autoconfigure.orm.jpa.TestEntityManager;

@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
class FeedbackRepositoryTest {

    @Autowired private FeedbackRepository repository;
    @Autowired private TestEntityManager entityManager;

    @Test
    void everyFieldSurvivesAReloadFromTheDatabase() {
        Instant before = Instant.now();
        Long id = entityManager.persistAndGetId(new Feedback("u1", 4, "useful"), Long.class);
        entityManager.flush();
        entityManager.clear();

        Feedback reloaded = repository.findById(id).orElseThrow(AssertionError::new);

        assertThat(reloaded.getId()).isEqualTo(id);
        assertThat(reloaded.getUserId()).isEqualTo("u1");
        assertThat(reloaded.getRating()).isEqualTo(4);
        assertThat(reloaded.getMessage()).isEqualTo("useful");
        assertThat(reloaded.getCreatedAt()).isAfterOrEqualTo(before.minusSeconds(1));
    }

    @Test
    void findByUserIdReturnsNewestFirstAndIgnoresOtherUsers() {
        entityManager.persist(new Feedback("u1", 1, "oldest"));
        entityManager.persist(new Feedback("u1", 5, "newest"));
        entityManager.persist(new Feedback("u2", 3, "someone else"));
        entityManager.flush();
        entityManager.clear();

        List<Feedback> forUser = repository.findByUserIdOrderByCreatedAtDesc("u1");

        assertThat(forUser).extracting(Feedback::getMessage).containsExactly("newest", "oldest");
    }

    @Test
    void findByUserIdIsEmptyForAnUnknownUser() {
        assertThat(repository.findByUserIdOrderByCreatedAtDesc("nobody")).isEmpty();
    }
}
