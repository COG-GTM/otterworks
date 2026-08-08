class AdminSettingsService
  AUTO_INVESTIGATE_KEY = 'admin:auto_investigate'.freeze
  DEVIN_API_KEY_KEY = 'admin:devin_api_key'.freeze
  DEVIN_ORG_ID_KEY = 'admin:devin_org_id'.freeze

  class << self
    def auto_investigate_enabled?
      redis = Redis.new(
        url: ENV.fetch('REDIS_URL', "redis://#{ENV.fetch('REDIS_HOST', 'localhost')}:#{ENV.fetch('REDIS_PORT', '6379')}/0"),
        timeout: 2
      )
      # Default to true (existing behavior) if not explicitly set
      val = redis.get(AUTO_INVESTIGATE_KEY)
      val.nil? ? true : val == 'true'
    rescue StandardError => e
      Rails.logger.error("Failed to read auto_investigate setting: #{e.message}")
      true # fail-open to preserve existing behavior
    ensure
      redis&.close
    end

    def set_auto_investigate(enabled)
      redis = Redis.new(
        url: ENV.fetch('REDIS_URL', "redis://#{ENV.fetch('REDIS_HOST', 'localhost')}:#{ENV.fetch('REDIS_PORT', '6379')}/0"),
        timeout: 2
      )
      redis.set(AUTO_INVESTIGATE_KEY, enabled.to_s)
    rescue StandardError => e
      Rails.logger.error("Failed to set auto_investigate setting: #{e.message}")
      raise
    ensure
      redis&.close
    end

    # Devin API credentials, stored in the tenant's Redis so they can be set
    # at runtime (via the settings API) without a redeploy. Values are never
    # exposed by any read path — only presence is reported.
    def devin_credentials
      redis = Redis.new(
        url: ENV.fetch('REDIS_URL', "redis://#{ENV.fetch('REDIS_HOST', 'localhost')}:#{ENV.fetch('REDIS_PORT', '6379')}/0"),
        timeout: 2
      )
      api_key, org_id = redis.mget(DEVIN_API_KEY_KEY, DEVIN_ORG_ID_KEY)
      { api_key: blank_to_nil(api_key), org_id: blank_to_nil(org_id) }
    rescue StandardError => e
      Rails.logger.error("Failed to read Devin credentials: #{e.message}")
      { api_key: nil, org_id: nil }
    ensure
      redis&.close
    end

    def set_devin_credentials(api_key:, org_id:)
      redis = Redis.new(
        url: ENV.fetch('REDIS_URL', "redis://#{ENV.fetch('REDIS_HOST', 'localhost')}:#{ENV.fetch('REDIS_PORT', '6379')}/0"),
        timeout: 2
      )
      redis.mset(DEVIN_API_KEY_KEY, api_key, DEVIN_ORG_ID_KEY, org_id)
    rescue StandardError => e
      Rails.logger.error("Failed to set Devin credentials: #{e.message}")
      raise
    ensure
      redis&.close
    end

    private

    def blank_to_nil(val)
      val.nil? || val.strip.empty? ? nil : val
    end
  end
end
