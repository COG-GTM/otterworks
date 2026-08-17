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
  # A failing read is remembered too, but briefly: a broken IRSA policy would
  # otherwise mean an AWS call per incident and per status check.
  ERROR_CACHE_TTL = 30
  MUTEX = Mutex.new

  class << self
    def enabled?
      secret_id.present?
    end

    def credentials
      return { api_key: nil, org_id: nil } unless enabled?

      # Read the memo once: another thread may drop it between the freshness
      # check and the use.
      cached = @cache
      return cached[:value] if fresh?(cached)

      # Puma serves requests on many threads; without this every concurrent
      # incident would race to refresh the same secret.
      MUTEX.synchronize do
        cached = @cache
        next cached[:value] if fresh?(cached)

        fetch(secret_id)
      end
    end

    # Rotation only takes effect after the TTL; this lets an operator (or a
    # spec) drop the memo immediately.
    def reset_cache!
      MUTEX.synchronize { @cache = nil }
    end

    private

    def secret_id
      ENV.fetch('DEVIN_CREDENTIALS_SECRET_ID', nil).presence
    end

    def fresh?(cached)
      return false if cached.nil? || cached[:secret_id] != secret_id

      ttl = cached[:error] ? ERROR_CACHE_TTL : CACHE_TTL
      cached[:fetched_at] > Time.now.to_f - ttl
    end

    def fetch(id)
      payload = JSON.parse(client.get_secret_value(secret_id: id).secret_string.to_s)
      value = {
        api_key: payload['api_key'].presence,
        org_id: payload['org_id'].presence
      }
      unless value[:api_key] && value[:org_id]
        # Half a pair is unusable and would look like "no Secrets Manager
        # wiring" at the status endpoint, so say so.
        Rails.logger.warn("Devin secret #{id} is missing api_key or org_id; falling back to the stored pair")
      end
      # An unusable payload is memoized too, so a misconfigured secret does not
      # mean an AWS call on every incident and status check.
      @cache = { secret_id: id, fetched_at: Time.now.to_f, value: value }
      value
    rescue StandardError => e
      Rails.logger.error("Failed to read Devin credentials from Secrets Manager: #{e.message}")
      # A Secrets Manager blip must not stop incident triage: keep serving the
      # last pair that worked, and fall through to the stored pair otherwise.
      value = @cache&.dig(:value) || { api_key: nil, org_id: nil }
      @cache = { secret_id: id, fetched_at: Time.now.to_f, value: value, error: true }
      value
    end

    def client
      @client ||= Aws::SecretsManager::Client.new(region: ENV.fetch('AWS_REGION', 'us-east-1'))
    end
  end
end
