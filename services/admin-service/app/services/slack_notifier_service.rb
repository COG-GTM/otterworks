require 'net/http'
require 'json'
require 'uri'

# Posts incident alerts to Slack. When a bot token is configured (the
# SLACK_BOT_TOKEN env var, or one stored at runtime via the settings API),
# delivery goes through chat.postMessage to the channel resolved by
# SlackAlertRoutes (default #automated-alerts); otherwise it falls back to an
# incoming webhook, whose channel is bound to the webhook itself. Every failure is
# logged and swallowed — a Slack outage must never block incident creation.
class SlackNotifierService
  # Slack Block Kit rejects the whole message (400 invalid_blocks) when a
  # header exceeds 150 chars, a section exceeds 3000 chars, or a section
  # field exceeds 2000 chars.
  HEADER_MAX = 150
  # Requires the bot-token prefix and rejects whitespace/control characters
  # (the CRLF-injection concern for the Authorization header) without
  # constraining the token alphabet, which Slack may extend.
  BOT_TOKEN_SHAPE = /\Axoxb-\S+\z/
  SECTION_MAX = 3000
  FIELD_MAX = 2000

  class << self
    def notify_incident(incident:, session_url: nil, reporter_email: nil, alert_name: nil)
      return unless AdminSettingsService.slack_notifications_enabled?

      channel = SlackAlertRoutes.channel_for(alert_name.presence || infer_alert_name(incident))
      payload = build_payload(incident, session_url, reporter_email)

      bot_token = resolve_bot_token
      return if bot_token && post_via_api(bot_token, channel, payload)

      webhook_url = resolve_webhook_url
      unless webhook_url
        if bot_token.nil?
          Rails.logger.info('Slack not configured (no bot token or webhook), skipping incident notification')
        end
        return
      end
      post_via_webhook(webhook_url, payload)
    rescue StandardError => e
      Rails.logger.error("Slack incident notification failed: #{e.message}")
      nil
    end

    def valid_bot_token?(token)
      token.to_s.match?(BOT_TOKEN_SHAPE)
    end

    private

    # chat.postMessage honors an explicit channel, unlike incoming webhooks,
    # so this is the path that guarantees delivery to the routed channel.
    # Returns whether Slack accepted the message. On a rejection or a
    # transport failure the caller retries via the webhook: a duplicate is
    # possible only in the narrow case where Slack accepted the message but
    # the response never arrived intact, and a rare duplicate alert beats a
    # silently dropped one.
    def post_via_api(bot_token, channel, payload)
      uri = URI('https://slack.com/api/chat.postMessage')
      request = Net::HTTP::Post.new(uri)
      request['Content-Type'] = 'application/json; charset=utf-8'
      request['Authorization'] = "Bearer #{bot_token}"
      request.body = payload.merge(channel: channel).to_json

      response = http_for(uri).request(request)
      if response.is_a?(Net::HTTPSuccess)
        body = JSON.parse(response.body) rescue {}
        return true if body['ok']

        Rails.logger.error("Slack chat.postMessage failed: #{body['error']}")
      else
        Rails.logger.error("Slack chat.postMessage returned #{response.code}: #{response.body.to_s[0, 200]}")
      end
      false
    rescue StandardError => e
      Rails.logger.error("Slack chat.postMessage raised #{e.class}: #{e.message}")
      false
    end

    def post_via_webhook(webhook_url, payload)
      uri = URI(webhook_url)
      request = Net::HTTP::Post.new(uri)
      request['Content-Type'] = 'application/json'
      request.body = payload.to_json

      response = http_for(uri).request(request)
      unless response.is_a?(Net::HTTPSuccess)
        Rails.logger.error("Slack webhook returned #{response.code}: #{response.body.to_s[0, 200]}")
      end
      nil
    end

    def http_for(uri)
      http = Net::HTTP.new(uri.host, uri.port)
      http.use_ssl = uri.scheme == 'https'
      http.open_timeout = 5
      http.read_timeout = 10
      http
    end

    # Alerts ingested via AlertsController carry an explicit alertname; for
    # incidents created elsewhere the leading "Type:" segment of the title
    # is the closest equivalent.
    def infer_alert_name(incident)
      incident.title.to_s.split(':').first.to_s.strip
    end

    # Environment wins; the Redis-backed settings store is the fallback so the
    # token can be supplied at runtime on tenants whose deploy pipeline does
    # not wire it as an env var. Like the stored webhook URL, the stored token
    # is re-validated at send time so a value planted in Redis outside the
    # settings API cannot reach the Authorization header or silently suppress
    # the webhook fallback.
    def resolve_bot_token
      ENV.fetch('SLACK_BOT_TOKEN', nil).presence || stored_bot_token
    end

    def stored_bot_token
      token = AdminSettingsService.slack_bot_token
      return nil unless token
      return token if valid_bot_token?(token)

      Rails.logger.error('Stored Slack bot token is not an xoxb- token, ignoring it')
      nil
    end

    # Environment wins; the Redis-backed settings store is the fallback so the
    # webhook can be supplied at runtime on tenants whose deploy pipeline does
    # not wire it as an env var. The stored URL is re-validated at send time
    # so a value planted in Redis outside the settings API cannot redirect
    # incident payloads to an arbitrary host.
    def resolve_webhook_url
      ENV.fetch('SLACK_WEBHOOK_URL', nil).presence || stored_webhook_url
    end

    def stored_webhook_url
      url = AdminSettingsService.slack_webhook_url
      return nil unless url

      uri = URI.parse(url)
      return url if uri.scheme == 'https' && uri.host.to_s.downcase == 'hooks.slack.com' && uri.userinfo.nil?

      Rails.logger.error('Stored Slack webhook URL is not a hooks.slack.com HTTPS URL, ignoring it')
      nil
    rescue URI::Error
      Rails.logger.error('Stored Slack webhook URL is not a valid URI, ignoring it')
      nil
    end

    def build_payload(incident, session_url, reporter_email)
      raw_service = incident.affected_service.presence || 'unknown-service'
      service = escape_mrkdwn(raw_service)
      title = escape_mrkdwn(incident.title)
      type = escape_mrkdwn(incident.title.to_s.split(':').first.to_s.strip)
      on_call_devin = if session_url.present?
                        ":robot_face: <#{session_url}|Devin AI (auto-investigating)>"
                      else
                        ':robot_face: No Devin session'
                      end
      on_call_fields = [field('On-Call', on_call_devin)]
      on_call_human = human_mention(reporter_email)
      on_call_fields << field('On-Call', on_call_human) if on_call_human

      # The description lives in its own code-block section; backticks are
      # stripped so it cannot terminate the fence. Slack parses <...> control
      # sequences (links, @-mentions, <!channel>) at the message level even
      # inside fences, so &, < and > must still be entity-escaped — Slack
      # renders the escaped entities back as the literal characters.
      description = truncate(
        escape_mrkdwn(incident.description.to_s.delete('`')),
        SECTION_MAX - "*Message:*\n``````".length
      )

      {
        # The top-level text is Slack's notification/fallback string; without
        # it, pushes and screen readers for a blocks-only message are blank.
        # It is parsed as mrkdwn, so it must be escaped like any other field.
        text: truncate("OtterWorks Alert — #{service} — #{title}", HEADER_MAX),
        blocks: [
          {
            type: 'header',
            text: {
              type: 'plain_text',
              text: truncate(":rotating_light: OtterWorks Alert — #{raw_service} — #{incident.title}", HEADER_MAX),
              emoji: true
            }
          },
          { type: 'section', fields: [field('Error', title), field('Severity', incident.severity)] },
          { type: 'section', fields: [field('Location', "`#{service}`"), field('Type', type)] },
          {
            type: 'section',
            text: { type: 'mrkdwn', text: "*Message:*\n```#{description}```" }
          },
          { type: 'section', fields: [field('Environment', Rails.env)] },
          { type: 'section', fields: on_call_fields },
          {
            type: 'context',
            elements: [
              {
                type: 'mrkdwn',
                text: "Service: `#{service}` | #{Time.current.utc.iso8601(3)}"
              }
            ]
          }
        ]
      }
    end

    def field(label, value)
      { type: 'mrkdwn', text: truncate("*#{label}:*\n#{value}", FIELD_MAX) }
    end

    # The incident's reporter is the second on-call line. A true @-mention
    # needs a Slack member id, resolved from the reporter's email via
    # SLACK_USER_MAP (a JSON object of email -> Slack member id) or, when a
    # bot token with users:read.email is configured, Slack's
    # users.lookupByEmail API; unresolvable reporters appear as their plain
    # email. SLACK_ONCALL_MEMBER (a Slack member id) is the fallback when the
    # incident has no reporter (e.g. Grafana-ingested alerts).
    def human_mention(reporter_email)
      if reporter_email.present?
        slack_id = slack_user_map[reporter_email] || lookup_member_id(reporter_email)
        return slack_id ? "<@#{slack_id}>" : escape_mrkdwn(reporter_email)
      end

      fallback = ENV.fetch('SLACK_ONCALL_MEMBER', nil).presence
      fallback ? "<@#{fallback}>" : nil
    end

    # Resolves an email to a Slack member id via users.lookupByEmail. Needs
    # the users:read.email scope on the bot token; any failure (missing
    # scope, unknown email, transport error) resolves to nil so the caller
    # falls back to rendering the plain email.
    def lookup_member_id(email)
      bot_token = resolve_bot_token
      return nil unless bot_token

      uri = URI('https://slack.com/api/users.lookupByEmail')
      uri.query = URI.encode_www_form(email: email)
      request = Net::HTTP::Get.new(uri)
      request['Authorization'] = "Bearer #{bot_token}"

      response = http_for(uri).request(request)
      unless response.is_a?(Net::HTTPSuccess)
        Rails.logger.warn("Slack users.lookupByEmail returned #{response.code}")
        return nil
      end

      body = JSON.parse(response.body) rescue {}
      unless body['ok']
        Rails.logger.info("Slack users.lookupByEmail failed: #{body['error']}")
        return nil
      end

      body.dig('user', 'id').presence
    rescue StandardError => e
      Rails.logger.warn("Slack users.lookupByEmail raised #{e.class}: #{e.message}")
      nil
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

    # Slack mrkdwn requires &, < and > to be HTML-escaped in text content.
    def escape_mrkdwn(text)
      text.to_s.gsub('&', '&amp;').gsub('<', '&lt;').gsub('>', '&gt;')
    end

    # Truncation happens after escaping, so a cut can land mid-entity
    # (e.g. "&am…"); the trailing partial entity is dropped rather than
    # rendered literally. Complete entities end in ";" and never match.
    def truncate(text, max)
      return text unless text.length > max

      "#{text[0, max - 1]}\u2026".sub(/&[a-z]{0,3}\u2026\z/, "\u2026")
    end
  end
end
