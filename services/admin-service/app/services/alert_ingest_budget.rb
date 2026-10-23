# Caps how many incidents per service per hour may skip alert de-duplication
# via the `dedup=false` label, so a burst of alerts cannot open an unbounded
# number of incidents (and Devin sessions).
class AlertIngestBudget
  KEY_PREFIX = 'alerts:dedup_bypass'.freeze
  WINDOW_SECONDS = 3600
  DEFAULT_LIMIT = 20

  class << self
    def allow_dedup_bypass?(affected_service)
      redis = Redis.new(url: ServiceEnv.redis_url, timeout: 2)
      key = "#{KEY_PREFIX}:#{affected_service}:#{Time.now.to_i / WINDOW_SECONDS}"
      count, = redis.multi do |tx|
        tx.incr(key)
        tx.expire(key, WINDOW_SECONDS)
      end
      count.to_i <= limit
    rescue StandardError => e
      Rails.logger.error("Alert dedup budget unavailable, de-duplicating: #{e.message}")
      false
    ensure
      redis&.close
    end

    def limit
      Integer(ENV.fetch('ALERT_DEDUP_BYPASS_PER_HOUR', DEFAULT_LIMIT))
    rescue ArgumentError, TypeError
      DEFAULT_LIMIT
    end
  end
end
