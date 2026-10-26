# Hourly budgets that stop a burst of ingested alerts from opening an
# unbounded number of incidents (via `dedup=false`) or paid Devin sessions.
# Counters live in the tenant's Redis; when Redis is unavailable the budget
# is treated as spent.
class AlertIngestBudget
  WINDOW_SECONDS = 3600
  DEFAULTS = {
    dedup_bypass: ['ALERT_DEDUP_BYPASS_PER_HOUR', 20],
    devin_session: ['ALERT_DEVIN_SESSIONS_PER_HOUR', 10]
  }.freeze

  class << self
    def allow_dedup_bypass?(affected_service)
      consume?(:dedup_bypass, "alerts:budget:dedup_bypass:#{affected_service}")
    end

    def allow_devin_session?
      consume?(:devin_session, 'alerts:budget:devin_session')
    end

    def limit(kind)
      env_name, default = DEFAULTS.fetch(kind)
      value = Integer(ENV.fetch(env_name, default))
      value.negative? ? default : value
    rescue ArgumentError, TypeError
      default
    end

    private

    def consume?(kind, key_prefix)
      redis = Redis.new(url: ServiceEnv.redis_url, timeout: 2)
      key = "#{key_prefix}:#{Time.now.to_i / WINDOW_SECONDS}"
      count, = redis.multi do |tx|
        tx.incr(key)
        tx.expire(key, WINDOW_SECONDS)
      end
      count.to_i <= limit(kind)
    rescue StandardError => e
      Rails.logger.error("Alert ingest budget #{kind} unavailable, treating as spent: #{e.message}")
      false
    ensure
      redis&.close
    end
  end
end
