Rails.application.config.after_initialize do
  JwtSecret.validate! unless Rails.env.test?
end
