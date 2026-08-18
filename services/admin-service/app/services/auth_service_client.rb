require 'net/http'

# Thin client for auth-service, the source of truth for per-user
# storage quotas (users.quota_bytes).
class AuthServiceClient
  def self.base_url
    host = ENV.fetch('AUTH_SERVICE_HOST', 'auth-service')
    port = ENV.fetch('AUTH_SERVICE_PORT', '8081')
    "http://#{host}:#{port}"
  end

  # Pushes the new quota to auth-service. Best-effort: returns true on
  # success, false when auth-service is unreachable or rejects the update.
  def self.update_quota(user_id:, quota_bytes:, authorization: nil)
    uri = URI.parse("#{base_url}/api/v1/auth/users/#{user_id}/quota")
    request = Net::HTTP::Patch.new(uri)
    request['Content-Type'] = 'application/json'
    request['Authorization'] = authorization if authorization.present?
    request.body = { quotaBytes: quota_bytes }.to_json

    http = Net::HTTP.new(uri.host, uri.port)
    http.open_timeout = 2
    http.read_timeout = 2
    response = http.request(request)
    return true if response.is_a?(Net::HTTPSuccess)

    Rails.logger.warn("auth-service quota sync rejected for #{user_id}: #{response.code} #{response.body}")
    false
  rescue StandardError => e
    Rails.logger.warn("auth-service quota sync failed for #{user_id}: #{e.message}")
    false
  end
end
