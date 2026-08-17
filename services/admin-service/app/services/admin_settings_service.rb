class AdminSettingsService
  AUTO_INVESTIGATE_KEY = 'admin:auto_investigate'.freeze
  DEVIN_API_KEY_KEY = 'admin:devin_api_key'.freeze
  DEVIN_ORG_ID_KEY = 'admin:devin_org_id'.freeze

  # Durable home for the same pair. The tenant's Redis runs with persistence
  # disabled (`--save "" --appendonly no`), so anything kept only there is gone
  # after a pod restart, eviction or idle scale-to-zero; Postgres survives.
  DEVIN_API_KEY_CONFIG = 'devin_api_key'.freeze
  DEVIN_ORG_ID_CONFIG = 'devin_org_id'.freeze
  LEGACY_DEVIN_KEYS = [DEVIN_API_KEY_KEY, DEVIN_ORG_ID_KEY].freeze

  class << self
    def auto_investigate_enabled?
      redis = Redis.new(
        url: ServiceEnv.redis_url,
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
        url: ServiceEnv.redis_url,
        timeout: 2
      )
      redis.set(AUTO_INVESTIGATE_KEY, enabled.to_s)
    rescue StandardError => e
      Rails.logger.error("Failed to set auto_investigate setting: #{e.message}")
      raise
    ensure
      redis&.close
    end

    # Devin API credentials, settable at runtime (via the settings API) without
    # a redeploy, and stored in Postgres so they outlive a Redis restart or a
    # redeploy. Values are never exposed by any read path — only presence is
    # reported.
    def devin_credentials
      stored = stored_devin_credentials
      return stored if stored[:api_key] && stored[:org_id]

      # Credentials loaded while Redis was the store live only there; adopt
      # them rather than losing session creation on the next restart.
      legacy = legacy_devin_credentials
      return stored unless legacy[:api_key] && legacy[:org_id]

      begin
        set_devin_credentials(api_key: legacy[:api_key], org_id: legacy[:org_id])
      rescue StandardError => e
        # Adoption is opportunistic: the caller still gets a usable pair, and a
        # failed read above must not turn a status check into a 500.
        Rails.logger.error("Failed to adopt legacy Devin credentials: #{e.message}")
      end
      legacy
    end

    def set_devin_credentials(api_key:, org_id:)
      # Half a pair is unusable and would silently resolve to "not configured"
      # at the next incident, so write both or neither.
      SystemConfig.transaction do
        write_config(DEVIN_API_KEY_CONFIG, api_key, 'Devin API key used for incident auto-triage')
        write_config(DEVIN_ORG_ID_CONFIG, org_id, 'Devin organization id used for incident auto-triage')
      end
      with_redis { |redis| redis.del(*LEGACY_DEVIN_KEYS) }
    end

    def clear_devin_credentials
      SystemConfig.where(key: [DEVIN_API_KEY_CONFIG, DEVIN_ORG_ID_CONFIG]).delete_all
      with_redis { |redis| redis.del(*LEGACY_DEVIN_KEYS) }
    end

    private

    def stored_devin_credentials
      values = SystemConfig.where(key: [DEVIN_API_KEY_CONFIG, DEVIN_ORG_ID_CONFIG])
                           .pluck(:key, :value).to_h
      {
        api_key: blank_to_nil(values[DEVIN_API_KEY_CONFIG]),
        org_id: blank_to_nil(values[DEVIN_ORG_ID_CONFIG])
      }
    rescue StandardError => e
      Rails.logger.error("Failed to read Devin credentials: #{e.message}")
      { api_key: nil, org_id: nil }
    end

    def legacy_devin_credentials
      api_key, org_id = with_redis { |redis| redis.mget(*LEGACY_DEVIN_KEYS) }
      { api_key: blank_to_nil(api_key), org_id: blank_to_nil(org_id) }
    end

    def write_config(key, value, description)
      config = SystemConfig.find_or_initialize_by(key: key)
      config.assign_attributes(value: value, value_type: 'string', is_secret: true, description: description)
      config.save!
    end

    # Redis only holds credentials left over from the old store, so its
    # failures must not fail the operation.
    def with_redis
      redis = Redis.new(url: ServiceEnv.redis_url, timeout: 2)
      yield redis
    rescue StandardError => e
      Rails.logger.warn("Devin credential cache unavailable: #{e.message}")
      nil
    ensure
      redis&.close
    end

    def blank_to_nil(val)
      val.nil? || val.strip.empty? ? nil : val
    end
  end
end
