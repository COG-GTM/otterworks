# Resolves the HMAC secret admin-service verifies JWTs with, and refuses to
# boot with one an attacker could know: anyone holding the secret can mint a
# token with `roles: ['OWNER']` and pass `require_admin!`.
module JwtSecret
  class InsecureSecretError < StandardError; end

  MIN_LENGTH = 32

  # Defaults that have shipped in this repository's compose file, service
  # configs and secrets.yml. They are public, so a token signed with one of
  # them proves nothing.
  KNOWN_DEFAULTS = %w[
    otterworks-local-dev-jwt-secret-change-me-in-production
    dev-jwt-secret-otterworks-2024-change-in-production
    otterworks-dev-secret
    dev_jwt_secret_key
    test_jwt_secret_key
  ].freeze

  module_function

  def current
    @current ||= resolve
  end

  def resolve(env: ENV, credentials: Rails.application.credentials, rails_env: Rails.env,
              test_fallback: -> { Rails.application.secrets.jwt_secret })
    configured = credentials.jwt_secret.presence || env['JWT_SECRET'].presence
    return validate!(configured) if configured

    # Only the test suite may use the checked-in secrets.yml value.
    return test_fallback.call if rails_env.to_s == 'test'

    raise InsecureSecretError,
          'JWT_SECRET is not set. Generate one with `openssl rand -hex 32` ' \
          '(or `make env` for docker compose) and pass it to every service.'
  end

  def validate!(secret)
    if KNOWN_DEFAULTS.include?(secret)
      raise InsecureSecretError,
            'JWT_SECRET is a default published in the OtterWorks repository; anyone can forge ' \
            'admin tokens with it. Set a random value (`openssl rand -hex 32`) and rotate any ' \
            'deployment that ran with the default.'
    end
    if secret.bytesize < MIN_LENGTH
      raise InsecureSecretError,
            "JWT_SECRET must be at least #{MIN_LENGTH} bytes (generate one with `openssl rand -hex 32`)."
    end

    secret
  end
end
