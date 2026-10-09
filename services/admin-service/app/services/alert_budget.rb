# Per-service caps on what alert ingest may create within a rolling window,
# counted from the incidents table so every admin-service process shares them:
#   - dedup bypass: how many incidents a trusted `dedup=false` alert may open
#     for one service before alerts collapse onto the open incident again.
#   - Devin sessions: how many billable sessions alert ingest may start for
#     one service.
module AlertBudget
  DEFAULT_WINDOW_SECONDS = 3600
  DEFAULT_MAX_INCIDENTS_PER_SERVICE = 10
  DEFAULT_MAX_DEVIN_SESSIONS_PER_SERVICE = 5

  class << self
    def dedup_bypass_allowed?(affected_service)
      recent_incidents(affected_service).count < max_incidents_per_service
    end

    def devin_session_allowed?(affected_service)
      recent_incidents(affected_service).where.not(devin_session_id: nil).count < max_devin_sessions_per_service
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

    def recent_incidents(affected_service)
      Incident.where(affected_service: affected_service)
              .where(created_at: window_seconds.seconds.ago..)
    end

    def positive_int_env(name, default)
      value = Integer(ENV.fetch(name, ''), exception: false)
      value&.positive? ? value : default
    end
  end
end
