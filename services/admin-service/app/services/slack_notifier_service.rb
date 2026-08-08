require 'net/http'
require 'json'
require 'uri'

# Posts incident alerts to a Slack channel via an incoming webhook. The
# channel is bound to the webhook itself. Every failure is logged and
# swallowed — a Slack outage must never block incident creation.
class SlackNotifierService
  # Slack Block Kit rejects the whole message (400 invalid_blocks) when a
  # header exceeds 150 chars or a section exceeds 3000 chars.
  HEADER_MAX = 150
  SECTION_MAX = 3000

  class << self
    def notify_incident(incident:, session_url: nil, reporter_email: nil)
      return unless AdminSettingsService.slack_notifications_enabled?

      webhook_url = resolve_webhook_url
      unless webhook_url
        Rails.logger.info('Slack webhook not configured, skipping incident notification')
        return
      end

      payload = build_payload(incident, session_url, reporter_email)

      uri = URI(webhook_url)
      request = Net::HTTP::Post.new(uri)
      request['Content-Type'] = 'application/json'
      request.body = payload.to_json

      http = Net::HTTP.new(uri.host, uri.port)
      http.use_ssl = uri.scheme == 'https'
      http.open_timeout = 5
      http.read_timeout = 10

      response = http.request(request)
      unless response.is_a?(Net::HTTPSuccess)
        Rails.logger.error("Slack webhook returned #{response.code}: #{response.body}")
      end
      nil
    rescue StandardError => e
      Rails.logger.error("Slack incident notification failed: #{e.message}")
      nil
    end

    private

    # Environment wins; the Redis-backed settings store is the fallback so the
    # webhook can be supplied at runtime on tenants whose deploy pipeline does
    # not wire it as an env var.
    def resolve_webhook_url
      ENV.fetch('SLACK_WEBHOOK_URL', nil).presence || AdminSettingsService.slack_webhook_url
    end

    def build_payload(incident, session_url, reporter_email)
      service = incident.affected_service.presence || 'unknown-service'
      on_call_devin = if session_url
                        "<#{session_url}|Devin AI (auto-investigating)>"
                      else
                        'No Devin session'
                      end
      on_call_human = human_mention(reporter_email)

      body_lines = [
        '*Error:*',
        incident.title,
        '*Severity:*',
        incident.severity,
        '*Location:*',
        service,
        '*Type:*',
        incident.title.split(':').first.to_s.strip,
        '*Message:*',
        incident.description,
        '*Environment:*',
        Rails.env,
        '*On-Call:*',
        on_call_devin
      ]
      body_lines += ['*On-Call:*', on_call_human] if on_call_human

      {
        blocks: [
          {
            type: 'header',
            text: {
              type: 'plain_text',
              text: truncate("OtterWorks Alert — #{service} — #{incident.title}", HEADER_MAX),
              emoji: true
            }
          },
          {
            type: 'section',
            text: { type: 'mrkdwn', text: truncate(body_lines.join("\n"), SECTION_MAX) }
          },
          {
            type: 'context',
            elements: [
              {
                type: 'mrkdwn',
                text: "Service: #{service} | #{Time.current.utc.iso8601(3)}"
              }
            ]
          }
        ]
      }
    end

    # The incident's reporter is the second on-call line. A true @-mention
    # needs a Slack member id, which an incoming webhook cannot look up from
    # an email, so SLACK_USER_MAP (a JSON object of email -> Slack member id)
    # provides the mapping; unmapped reporters appear as their plain email.
    # SLACK_ONCALL_MEMBER (a Slack member id) is the fallback when the
    # incident has no reporter (e.g. Grafana-ingested alerts).
    def human_mention(reporter_email)
      if reporter_email.present?
        slack_id = slack_user_map[reporter_email]
        return slack_id ? "<@#{slack_id}>" : reporter_email
      end

      fallback = ENV.fetch('SLACK_ONCALL_MEMBER', nil).presence
      fallback ? "<@#{fallback}>" : nil
    end

    def slack_user_map
      raw = ENV.fetch('SLACK_USER_MAP', nil).presence
      return {} unless raw

      parsed = JSON.parse(raw)
      return parsed if parsed.is_a?(Hash)

      Rails.logger.error('SLACK_USER_MAP must be a JSON object of email -> Slack member id')
      {}
    rescue JSON::ParserError => e
      Rails.logger.error("SLACK_USER_MAP is not valid JSON: #{e.message}")
      {}
    end

    def truncate(text, max)
      text.length > max ? "#{text[0, max - 1]}\u2026" : text
    end
  end
end
