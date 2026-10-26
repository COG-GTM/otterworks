# The alert ingest webhook rejects every alert until ALERT_WEBHOOK_SECRET is
# set (see AlertWebhookAuth); say so at boot rather than on the first alert.
Rails.application.config.after_initialize do
  if Rails.env.production? && AlertWebhookAuth.configured_secret.nil?
    Rails.logger.warn('ALERT_WEBHOOK_SECRET is unset or a public default: ' \
                      '/api/v1/admin/alerts/ingest will reject all alerts')
  end
end
