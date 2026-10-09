# Resolves the HMAC secret shared with auth-service and the API gateway, and
# refuses placeholder values that have been published in this repository.
module JwtSecret
  KNOWN_INSECURE = %w[
    otterworks-local-dev-jwt-secret-change-me-in-production
    dev-jwt-secret-otterworks-2024-change-in-production
    dev_jwt_secret_key
    dev_jwt_secret
  ].freeze

  class InsecureSecretError < StandardError; end

  module_function

  def current
    Rails.application.credentials.jwt_secret || ENV.fetch('JWT_SECRET', Rails.application.secrets.jwt_secret)
  end

  def validate!(secret = current)
    if secret.to_s.strip.empty?
      raise InsecureSecretError, 'JWT_SECRET is required but not set (run `make env` for local development)'
    end
    return unless KNOWN_INSECURE.include?(secret)

    raise InsecureSecretError,
          'JWT_SECRET is set to a publicly known placeholder; generate one with `openssl rand -hex 32`'
  end
end
