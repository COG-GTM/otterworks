-- Composite indexes backing the bounded SQL aggregations in PostgresMetricsRepository:
-- period-windowed top-content/active-users/export scans and per-user recent activity.
CREATE INDEX IF NOT EXISTS idx_analytics_events_type_occurred
    ON analytics_events (resource_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_analytics_events_user_occurred
    ON analytics_events (user_id, occurred_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_event_type_user
    ON analytics_events (event_type, user_id);
