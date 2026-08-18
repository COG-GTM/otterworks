class AdminSettingsService
  AUTO_INVESTIGATE_KEY = 'admin:auto_investigate'.freeze
  DEVIN_API_KEY_KEY = 'admin:devin_api_key'.freeze
  DEVIN_ORG_ID_KEY = 'admin:devin_org_id'.freeze
  SLACK_NOTIFICATIONS_KEY = 'admin:slack_notifications'.freeze
  SLACK_WEBHOOK_URL_KEY = 'admin:slack_webhook_url'.freeze
  SLACK_BOT_TOKEN_KEY = 'admin:slack_bot_token'.freeze

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

    # Devin API credentials, stored in the tenant's Redis so they can be set
    # at runtime (via the settings API) without a redeploy. Values are never
    # exposed by any read path — only presence is reported.
    def devin_credentials
      redis = Redis.new(
        url: ServiceEnv.redis_url,
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
        url: ServiceEnv.redis_url,
        timeout: 2
      )
      redis.mset(DEVIN_API_KEY_KEY, api_key, DEVIN_ORG_ID_KEY, org_id)
    rescue StandardError => e
      Rails.logger.error("Failed to set Devin credentials: #{e.message}")
      raise
    ensure
      redis&.close
    end

    def clear_devin_credentials
      redis = Redis.new(
        url: ServiceEnv.redis_url,
        timeout: 2
      )
      redis.del(DEVIN_API_KEY_KEY, DEVIN_ORG_ID_KEY)
    rescue StandardError => e
      Rails.logger.error("Failed to clear Devin credentials: #{e.message}")
      raise
    ensure
      redis&.close
    end

    def slack_notifications_enabled?
      redis = Redis.new(
        url: ServiceEnv.redis_url,
        timeout: 2
      )
      # Default to true if not explicitly set
      val = redis.get(SLACK_NOTIFICATIONS_KEY)
      val.nil? ? true : val == 'true'
    rescue StandardError => e
      Rails.logger.error("Failed to read slack_notifications setting: #{e.message}")
      true # fail-open: an unreachable Redis should not silence alerts
    ensure
      redis&.close
    end

    def set_slack_notifications(enabled)
      redis = Redis.new(
        url: ServiceEnv.redis_url,
        timeout: 2
      )
      redis.set(SLACK_NOTIFICATIONS_KEY, enabled.to_s)
    rescue StandardError => e
      Rails.logger.error("Failed to set slack_notifications setting: #{e.message}")
      raise
    ensure
      redis&.close
    end

    # Slack incoming-webhook URL, stored in the tenant's Redis so it can be set
    # at runtime without a redeploy. The value is never exposed by any read
    # path — only presence is reported.
    def slack_webhook_url
      redis = Redis.new(
        url: ServiceEnv.redis_url,
        timeout: 2
      )
      blank_to_nil(redis.get(SLACK_WEBHOOK_URL_KEY))
    rescue StandardError => e
      Rails.logger.error("Failed to read Slack webhook URL: #{e.message}")
      nil
    ensure
      redis&.close
    end

    def set_slack_webhook_url(url)
      redis = Redis.new(
        url: ServiceEnv.redis_url,
        timeout: 2
      )
      redis.set(SLACK_WEBHOOK_URL_KEY, url)
    rescue StandardError => e
      Rails.logger.error("Failed to set Slack webhook URL: #{e.message}")
      raise
    ensure
      redis&.close
    end

    def clear_slack_webhook_url
      redis = Redis.new(
        url: ServiceEnv.redis_url,
        timeout: 2
      )
      redis.del(SLACK_WEBHOOK_URL_KEY)
    rescue StandardError => e
      Rails.logger.error("Failed to clear Slack webhook URL: #{e.message}")
      raise
    ensure
      redis&.close
    end

    # Slack bot token, stored in the tenant's Redis so it can be set at
    # runtime without a redeploy. The value is never exposed by any read
    # path — only presence is reported.
    def slack_bot_token
      redis = Redis.new(
        url: ServiceEnv.redis_url,
        timeout: 2
      )
      blank_to_nil(redis.get(SLACK_BOT_TOKEN_KEY))
    rescue StandardError => e
      Rails.logger.error("Failed to read Slack bot token: #{e.message}")
      nil
    ensure
      redis&.close
    end

    def set_slack_bot_token(token)
      redis = Redis.new(
        url: ServiceEnv.redis_url,
        timeout: 2
      )
      redis.set(SLACK_BOT_TOKEN_KEY, token)
    rescue StandardError => e
      Rails.logger.error("Failed to set Slack bot token: #{e.message}")
      raise
    ensure
      redis&.close
    end

    def clear_slack_bot_token
      redis = Redis.new(
        url: ServiceEnv.redis_url,
        timeout: 2
      )
      redis.del(SLACK_BOT_TOKEN_KEY)
    rescue StandardError => e
      Rails.logger.error("Failed to clear Slack bot token: #{e.message}")
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
