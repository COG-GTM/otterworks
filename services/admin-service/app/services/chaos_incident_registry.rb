# Remembers which incidents the alert pipeline opened for a service while
# that service's chaos flag was set, so chaos reset resolves only those
# incidents and never one it cannot attribute to a chaos run.
class ChaosIncidentRegistry
  TTL_SECONDS = 7 * 24 * 3600

  def self.key(service)
    "chaos_incidents:#{service}"
  end

  def self.flag_key(service)
    scenario = Api::V1::Admin::ChaosController::VALID_SCENARIOS[service]
    scenario && "chaos:#{service}:#{scenario}"
  end

  # Called by the alert pipeline for every incident it opens. Returns true
  # when the incident was attributed to an active chaos flag.
  def self.record(incident)
    flag = flag_key(incident.affected_service)
    return false unless flag

    with_redis do |redis|
      next false unless redis.exists?(flag)

      redis.sadd(key(incident.affected_service), incident.id)
      redis.expire(key(incident.affected_service), TTL_SECONDS)
      true
    end
  rescue StandardError => e
    Rails.logger.warn("ChaosIncidentRegistry.record failed for incident #{incident.id}: #{e.class} - #{e.message}")
    false
  end

  # Incident ids attributed to chaos runs on the service.
  def self.ids(redis, service)
    redis.smembers(key(service))
  end

  def self.with_redis
    redis = Redis.new(url: ServiceEnv.redis_url, timeout: 2)
    yield redis
  ensure
    redis&.close
  end
end
