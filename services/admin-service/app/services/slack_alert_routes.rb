require 'yaml'

# Declarative Slack routing, loaded from config/slack_alerts.yml. Each alert
# type (Grafana `alertname`) may declare its own route; unknown or missing
# alert names fall back to the `default` route, so a new chaos error works
# with zero configuration and can be customized with one YAML entry.
class SlackAlertRoutes
  CONFIG_PATH = Rails.root.join('config', 'slack_alerts.yml')
  FALLBACK_CHANNEL = '#automated-alerts'.freeze

  class << self
    def channel_for(alert_name)
      route_for(alert_name)['channel'].presence || FALLBACK_CHANNEL
    end

    def route_for(alert_name)
      defaults = config.fetch('default', {})
      overrides = config.fetch('alerts', {})[alert_name.to_s] || {}
      defaults.merge(overrides)
    end

    def reset!
      @config = nil
    end

    private

    def config
      @config ||= load_config
    end

    def load_config
      loaded = YAML.safe_load_file(CONFIG_PATH)
      loaded.is_a?(Hash) ? loaded : {}
    rescue StandardError => e
      Rails.logger.error("Failed to load #{CONFIG_PATH}: #{e.message}")
      {}
    end
  end
end
