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
      channel = route_for(alert_name)['channel']
      channel.is_a?(String) && channel.present? ? channel : FALLBACK_CHANNEL
    end

    # Sections left empty in the YAML parse as nil, and entries may be
    # malformed scalars, so every layer is coerced to a Hash before merging.
    def route_for(alert_name)
      defaults = as_hash(config['default'])
      overrides = as_hash(as_hash(config['alerts'])[alert_name.to_s])
      defaults.merge(overrides)
    end

    def reset!
      @config = nil
    end

    private

    def as_hash(value)
      value.is_a?(Hash) ? value : {}
    end

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
