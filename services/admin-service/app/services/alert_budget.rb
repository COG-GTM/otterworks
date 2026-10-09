# Per-service caps on what alert ingest may create within a rolling window.
# Each slot is an AlertBudgetReservation row claimed under a per-service
# Postgres advisory lock, so concurrent requests and processes cannot
# overshoot, and incidents/sessions created outside alert ingest don't count.
#   - incident: incidents alert ingest may open for one service.
#   - devin_session: billable Devin sessions alert ingest may start for one service.
module AlertBudget
  DEFAULT_WINDOW_SECONDS = 3600
  DEFAULT_MAX_INCIDENTS_PER_SERVICE = 10
  DEFAULT_MAX_DEVIN_SESSIONS_PER_SERVICE = 5

  class << self
    def reserve_incident(affected_service)
      reserve('incident', affected_service, max_incidents_per_service)
    end

    def reserve_devin_session(affected_service)
      reserve('devin_session', affected_service, max_devin_sessions_per_service)
    end

    def window_seconds
      positive_int_env('ALERT_BUDGET_WINDOW_SECONDS', DEFAULT_WINDOW_SECONDS)
    end

    def max_incidents_per_service
      positive_int_env('ALERT_MAX_INCIDENTS_PER_SERVICE', DEFAULT_MAX_INCIDENTS_PER_SERVICE)
    end

    def max_devin_sessions_per_service
      positive_int_env('ALERT_MAX_DEVIN_SESSIONS_PER_SERVICE', DEFAULT_MAX_DEVIN_SESSIONS_PER_SERVICE)
    end

    private

    def reserve(kind, affected_service, limit)
      AlertBudgetReservation.transaction do
        lock_key = AlertBudgetReservation.connection.quote("alert_budget:#{kind}:#{affected_service}")
        AlertBudgetReservation.connection.execute("SELECT pg_advisory_xact_lock(hashtext(#{lock_key}))")

        scope = AlertBudgetReservation.where(kind: kind, affected_service: affected_service)
        cutoff = window_seconds.seconds.ago
        scope.where(created_at: ...cutoff).delete_all
        next false if scope.count >= limit

        scope.create!
        true
      end
    end

    def positive_int_env(name, default)
      value = Integer(ENV.fetch(name, ''), exception: false)
      value&.positive? ? value : default
    end
  end
end
