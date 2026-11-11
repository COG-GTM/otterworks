# Fail fast instead of booting an admin API that cannot verify tokens (or that
# someone later "fixes" with a guessable default). Development and test boot
# without it; the authenticator then rejects every token.
unless Rails.env.local?
  if Rails.application.credentials.jwt_secret.blank? && ENV['JWT_SECRET'].blank?
    raise 'JWT_SECRET must be set outside development/test'
  end
end
