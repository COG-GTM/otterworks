package com.otterworks.report.config;

import jakarta.persistence.EntityManagerFactory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.sql.DatabaseMetaData;
import java.util.List;
import java.util.Map;

/**
 * Inlines {@code reports.error_message} values written by the Boot 2 / Hibernate 5 build.
 *
 * That build mapped the column as {@code @Lob}, so on PostgreSQL the {@code text} column
 * holds a large-object OID and the message lives in {@code pg_largeobject}. The entity now
 * reads the column as plain text, so on startup each such row gets its message copied back
 * into the column. Rows already holding text are untouched; a value is only treated as an OID
 * when a large object with that OID exists. Large objects are never unlinked: the orphans are
 * left for an operator to remove with {@code vacuumlo}. Each row is updated on its own, so a
 * row whose large object is not valid UTF-8 is skipped with a warning and keeps its OID.
 */
@Component
public class LegacyErrorMessageMigration implements InitializingBean {

    private static final Logger logger = LoggerFactory.getLogger(LegacyErrorMessageMigration.class);

    private static final String LEGACY_ROWS =
            "SELECT r.id, r.error_message FROM reports r "
                    + "JOIN pg_largeobject_metadata m ON m.oid::text = r.error_message "
                    + "WHERE r.error_message ~ '^[0-9]+$'";

    private static final String INLINE_ROW =
            "UPDATE reports SET error_message = convert_from(lo_get(?::oid), 'UTF8') "
                    + "WHERE id = ? AND error_message = ?";

    private final JdbcTemplate jdbcTemplate;

    // EntityManagerFactory is injected so Hibernate's schema update has run first.
    public LegacyErrorMessageMigration(JdbcTemplate jdbcTemplate, EntityManagerFactory entityManagerFactory) {
        this.jdbcTemplate = jdbcTemplate;
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
        List<Map<String, Object>> rows;
        try {
            rows = jdbcTemplate.queryForList(LEGACY_ROWS);
        } catch (DataAccessException e) {
            logger.warn("Could not look up legacy large-object error_message values: {}", e.getMessage());
            return;
        }
        int migrated = 0;
        for (Map<String, Object> row : rows) {
            Object id = row.get("id");
            String oid = (String) row.get("error_message");
            try {
                migrated += jdbcTemplate.update(INLINE_ROW, oid, id, oid);
            } catch (DataAccessException e) {
                logger.warn("Skipped legacy error_message for report {} (large object {}): {}",
                        id, oid, e.getMostSpecificCause().getMessage());
            }
        }
        if (migrated > 0) {
            logger.info("Inlined {} legacy large-object error_message value(s) in reports; "
                    + "the large objects are kept (remove orphans with vacuumlo)", migrated);
        }
    }
}
