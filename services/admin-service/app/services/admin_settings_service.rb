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

  # Durable tombstone: a revoke must stick even if the leftover Redis copy
  # cannot be deleted at that moment, so adoption is suppressed from Postgres
  # rather than from the availability of the cache.
  DEVIN_REVOKED_CONFIG = 'devin_credentials_revoked'.freeze

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

      if devin_credentials_revoked?
        # Otherwise a pair left in the old Redis keys is ignored with no trace,
        # which reads as "the store lost my credentials".
        Rails.logger.info('Devin credentials are revoked; ignoring any legacy Redis copy')
        return stored
      end

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
        SystemConfig.where(key: DEVIN_REVOKED_CONFIG).delete_all
      end
      with_redis { |redis| redis.del(*LEGACY_DEVIN_KEYS) }
    end

    # Revocation always takes effect: the durable rows go away and a tombstone
    # blocks re-adoption, so a Redis outage can delay cleanup of the leftover
    # copy but never keep a revoked key in use. Returns false when that copy
    # could not be deleted.
    def clear_devin_credentials
      SystemConfig.transaction do
        SystemConfig.where(key: [DEVIN_API_KEY_CONFIG, DEVIN_ORG_ID_CONFIG]).delete_all
        write_config(DEVIN_REVOKED_CONFIG, 'true', 'Devin credentials were revoked; ignore any cached copy')
      end
      !with_redis { |redis| redis.del(*LEGACY_DEVIN_KEYS) }.nil?
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

    def uniqueness_conflict?(error)
      error.record.errors.of_kind?(:key, :taken)
    end

    def devin_credentials_revoked?
      SystemConfig.exists?(key: DEVIN_REVOKED_CONFIG)
    rescue StandardError => e
      # Fail closed: an unreadable tombstone during a database blip must not let
      # a revoked pair be adopted back out of the legacy Redis keys.
      Rails.logger.error("Failed to read the Devin revocation marker; treating credentials as revoked: #{e.message}")
      true
    end

    def legacy_devin_credentials
      api_key, org_id = with_redis { |redis| redis.mget(*LEGACY_DEVIN_KEYS) }
      { api_key: blank_to_nil(api_key), org_id: blank_to_nil(org_id) }
    end

    def write_config(key, value, description)
      attrs = { value: value, value_type: 'string', is_secret: true, description: description }
      # Savepoint so a losing insert race does not poison the enclosing
      # transaction before the update retry.
      SystemConfig.transaction(requires_new: true) do
        SystemConfig.find_or_initialize_by(key: key).update!(attrs)
      end
    rescue ActiveRecord::RecordNotUnique, ActiveRecord::RecordInvalid => e
      # Only a lost insert race is retryable; a real validation failure has no
      # row to update and must surface as itself rather than as a 404.
      raise if e.is_a?(ActiveRecord::RecordInvalid) && !uniqueness_conflict?(e)

      row = SystemConfig.find_by(key: key)
      # The racing insert may not have committed yet, in which case there is
      # nothing to update: report the conflict rather than a 404.
      raise e if row.nil?

      row.update!(attrs)
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
