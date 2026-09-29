package com.otterworks.feedback;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.jdbc.core.JdbcTemplate;

/** The schema is owned by Flyway (Hibernate only validates), and lives in this service's schema. */
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
class FlywaySchemaTest {

    @Autowired private JdbcTemplate jdbc;

    @Test
    void v1IsAppliedToTheOwnedSchema() {
        Integer applied =
                jdbc.queryForObject(
                        "SELECT COUNT(*) FROM \"feedback\".\"flyway_schema_history\""
                                + " WHERE \"version\" = '1' AND \"success\" = TRUE",
                        Integer.class);
        assertThat(applied).isEqualTo(1);
        Integer tables =
                jdbc.queryForObject(
                        "SELECT COUNT(*) FROM information_schema.tables"
                                + " WHERE table_schema = 'feedback' AND table_name = 'feedback'",
                        Integer.class);
        assertThat(tables).isEqualTo(1);
    }
}
