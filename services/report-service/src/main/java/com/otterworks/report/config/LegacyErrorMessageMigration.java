package com.otterworks.report.config;

import jakarta.persistence.EntityManagerFactory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

import java.sql.DatabaseMetaData;
import java.util.List;

/**
 * Inlines {@code reports.error_message} values written by the Boot 2 / Hibernate 5 build.
 *
 * That build mapped the column as {@code @Lob}, so on PostgreSQL the {@code text} column
 * holds a large-object OID and the message lives in {@code pg_largeobject}. The entity now
 * reads the column as plain text, so on startup each such row gets its message copied back
 * into the column and the large object is unlinked. Rows already holding text are untouched;
 * a value is only treated as an OID when a large object with that OID exists.
 */
@Component
public class LegacyErrorMessageMigration implements InitializingBean {

    private static final Logger logger = LoggerFactory.getLogger(LegacyErrorMessageMigration.class);

    private static final String LEGACY_ROWS =
            "FROM reports r JOIN pg_largeobject_metadata m ON m.oid::text = r.error_message "
                    + "WHERE r.error_message ~ '^[0-9]+$'";

    private final JdbcTemplate jdbcTemplate;
    private final TransactionTemplate transactionTemplate;

    // EntityManagerFactory is injected so Hibernate's schema update has run first.
    public LegacyErrorMessageMigration(JdbcTemplate jdbcTemplate, TransactionTemplate transactionTemplate,
                                       EntityManagerFactory entityManagerFactory) {
        this.jdbcTemplate = jdbcTemplate;
        this.transactionTemplate = transactionTemplate;
    }

    @Override
    public void afterPropertiesSet() {
        String product = jdbcTemplate.execute((java.sql.Connection c) -> {
            DatabaseMetaData metaData = c.getMetaData();
            return metaData.getDatabaseProductName();
        });
        if (!"PostgreSQL".equals(product)) {
            return;
        }
        try {
            Integer migrated = transactionTemplate.execute(status -> {
                List<Long> oids = jdbcTemplate.queryForList("SELECT DISTINCT m.oid::bigint " + LEGACY_ROWS, Long.class);
                if (oids.isEmpty()) {
                    return 0;
                }
                int rows = jdbcTemplate.update("UPDATE reports r SET error_message = convert_from(lo_get(m.oid), 'UTF8') "
                        + "FROM pg_largeobject_metadata m WHERE m.oid::text = r.error_message AND r.error_message ~ '^[0-9]+$'");
                for (Long oid : oids) {
                    jdbcTemplate.queryForObject("SELECT lo_unlink(?::oid)", Integer.class, oid);
                }
                return rows;
            });
            if (migrated != null && migrated > 0) {
                logger.info("Inlined {} legacy large-object error_message value(s) in reports", migrated);
            }
        } catch (DataAccessException e) {
            logger.warn("Could not inline legacy large-object error_message values: {}", e.getMessage());
        }
    }
}
