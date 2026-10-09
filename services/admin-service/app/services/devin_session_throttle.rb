# Caps how many Devin sessions alert ingest may start per hour, so a burst of
# alerts (or a leaked webhook secret) cannot fan out into unbounded sessions.
class DevinSessionThrottle
  KEY_PREFIX = 'admin:devin_sessions'.freeze
  WINDOW_SECONDS = 3600
  DEFAULT_LIMIT = 20

  class << self
    # Returns true when a session may be started. Fails closed: if Redis is
    # unreachable no session is started.
    def acquire
      redis = Redis.new(url: ServiceEnv.redis_url, timeout: 2)
      key = "#{KEY_PREFIX}:#{Time.now.to_i / WINDOW_SECONDS}"
      count = redis.incr(key)
      redis.expire(key, WINDOW_SECONDS) if count == 1
      count <= limit
    rescue StandardError => e
      Rails.logger.error("Devin session throttle unavailable: #{e.message}")
      false
    ensure
      redis&.close
    end

    def limit
      Integer(ENV.fetch('ALERT_DEVIN_SESSIONS_PER_HOUR', DEFAULT_LIMIT))
    rescue ArgumentError, TypeError
      DEFAULT_LIMIT
    end
  end
end
