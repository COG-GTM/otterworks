require 'aws-sdk-secretsmanager'
require 'json'

# Reads the Devin credential pair from AWS Secrets Manager when
# DEVIN_CREDENTIALS_SECRET_ID names a secret. The pod already assumes a
# per-service IRSA role, so nothing has to be handed to the tenant by hand and
# the key is never written to Postgres, a ConfigMap or a Helm value.
#
# Expected secret payload:
#   {"api_key": "...", "org_id": "..."}
class DevinSecretsManagerSource
  CACHE_TTL = 300

  class << self
    def enabled?
      secret_id.present?
    end

    def credentials
      return { api_key: nil, org_id: nil } unless enabled?
      return @cache[:value] if fresh_cache?

      fetch(secret_id)
    end

    # Rotation only takes effect after the TTL; this lets an operator (or a
    # spec) drop the memo immediately.
    def reset_cache!
      @cache = nil
    end

    private

    def secret_id
      ENV.fetch('DEVIN_CREDENTIALS_SECRET_ID', nil).presence
    end

    def fresh_cache?
      @cache.present? &&
        @cache[:secret_id] == secret_id &&
        @cache[:fetched_at] > Time.now.to_f - CACHE_TTL
    end

    def fetch(id)
      payload = JSON.parse(client.get_secret_value(secret_id: id).secret_string.to_s)
      value = {
        api_key: payload['api_key'].presence,
        org_id: payload['org_id'].presence
      }
      @cache = { secret_id: id, fetched_at: Time.now.to_f, value: value } if value[:api_key] && value[:org_id]
      value
    rescue StandardError => e
      Rails.logger.error("Failed to read Devin credentials from Secrets Manager: #{e.message}")
      # A Secrets Manager blip must not stop incident triage: keep serving the
      # last pair that worked, and fall through to the stored pair otherwise.
      @cache&.fetch(:value, nil) || { api_key: nil, org_id: nil }
    end

    def client
      @client ||= Aws::SecretsManager::Client.new(region: ENV.fetch('AWS_REGION', 'us-east-1'))
    end
  end
end
