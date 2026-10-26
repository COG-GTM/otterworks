# Caps how many incidents (and therefore Devin sessions) alerts that opt out
# of dedup (`dedup=false`) may open per reporter in a rolling window. An
# alert over budget, or one whose budget cannot be checked because Redis is
# unreachable, falls back to normal dedup instead of opening a new incident,
# so a single user cannot open unlimited sessions by repeating a failure.
class AlertIncidentBudget
  KEY_PREFIX = 'admin:alert_dedup_bypass'.freeze
  DEFAULT_LIMIT = 5
  DEFAULT_WINDOW_SECONDS = 3600

  class << self
    def allow?(alert_name:, affected_service:, reporter_email:)
      key = budget_key(alert_name, affected_service, reporter_email)
      redis = Redis.new(url: ServiceEnv.redis_url, timeout: 2)
      redis.set(key, 0, ex: window_seconds, nx: true)
      redis.incr(key) <= limit
    rescue StandardError => e
      Rails.logger.error("Alert incident budget unavailable, falling back to dedup: #{e.message}")
      false
    ensure
      redis&.close
    end

    def limit
      positive_int_env('ALERT_DEDUP_BYPASS_LIMIT', DEFAULT_LIMIT)
    end

    def window_seconds
      positive_int_env('ALERT_DEDUP_BYPASS_WINDOW_SECONDS', DEFAULT_WINDOW_SECONDS)
    end

    private

    def budget_key(alert_name, affected_service, reporter_email)
      reporter = reporter_email.to_s.strip.downcase.presence || 'anonymous'
      digest = Digest::SHA256.hexdigest([alert_name.to_s, affected_service.to_s, reporter].join("\0"))
      "#{KEY_PREFIX}:#{digest}"
    end

    def positive_int_env(name, default)
      value = Integer(ENV.fetch(name, nil).to_s, exception: false)
      value&.positive? ? value : default
    end
  end
end
