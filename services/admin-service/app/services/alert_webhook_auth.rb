# Shared-secret check for the alert ingest webhook, which skips JWT auth.
# Fails closed: with no secret configured every alert is rejected, and in
# production a value that once shipped as a public default is never accepted.
module AlertWebhookAuth
  PUBLIC_DEFAULTS = %w[demo-alert-secret].freeze

  module_function

  def configured_secret
    secret = ENV.fetch('ALERT_WEBHOOK_SECRET', nil).to_s.strip
    return nil if secret.empty?
    return nil if Rails.env.production? && PUBLIC_DEFAULTS.include?(secret)

    secret
  end

  def authorized?(provided)
    expected = configured_secret
    return false if expected.nil? || provided.to_s.empty?

    ActiveSupport::SecurityUtils.secure_compare(provided.to_s, expected)
  end
end
