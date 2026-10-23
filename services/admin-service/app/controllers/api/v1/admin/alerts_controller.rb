module Api
  module V1
    module Admin
      # Receives Grafana Unified Alerting webhook payloads and converts them
      # into Incident records with an auto-triggered Devin session.
      #
      # Grafana POST body shape:
      #   {
      #     "receiver": "otterworks-webhook",
      #     "status": "firing" | "resolved",
      #     "alerts": [
      #       {
      #         "status": "firing" | "resolved",
      #         "labels": { "alertname": "...", "severity": "...", "affected_service": "..." },
      #         "annotations": { "summary": "...", "description": "..." },
      #         "startsAt": "2024-01-01T00:00:00Z"
      #       }
      #     ]
      #   }
      class AlertsController < ApplicationController
        before_action :verify_alert_secret

        # Values that were committed as defaults and must never authenticate.
        RETIRED_SECRETS = %w[demo-alert-secret].freeze

        MAX_ALERTS_PER_REQUEST = 50
        MAX_ALERT_NAME_LENGTH  = 128
        MAX_SUMMARY_LENGTH     = 200
        MAX_DESCRIPTION_LENGTH = 4_000

        # `dedup=false` alerts open one incident (and Devin session) each; cap
        # how many a single service can open per window.
        DEDUP_BYPASS_WINDOW = 10.minutes
        DEFAULT_DEDUP_BYPASS_LIMIT = 10

        SEVERITY_MAP = {
          'critical' => 'critical',
          'high'     => 'high',
          'warning'  => 'medium',
          'info'     => 'low',
        }.freeze

        # POST /api/v1/admin/alerts/ingest
        def ingest
          alerts = params[:alerts]
          unless alerts.is_a?(Array)
            return render json: { error: 'Missing alerts array' }, status: :bad_request
          end
          if alerts.size > MAX_ALERTS_PER_REQUEST
            return render json: { error: "Too many alerts (max #{MAX_ALERTS_PER_REQUEST})" },
                          status: :payload_too_large
          end

          processed = alerts.map { |alert| process_alert(alert) }.compact

          render json: { received: alerts.size, processed: processed.size, incidents: processed }
        end

        private

        def process_alert(alert)
          status           = alert[:status].to_s
          labels           = alert[:labels] || {}
          annotations      = alert[:annotations] || {}
          alert_name       = sanitize_text(labels[:alertname], MAX_ALERT_NAME_LENGTH, single_line: true)
          affected_service = labels[:affected_service].to_s.presence || labels[:service].to_s.presence
          severity         = SEVERITY_MAP.fetch(labels[:severity].to_s, 'medium')
          summary          = sanitize_text(annotations[:summary], MAX_SUMMARY_LENGTH, single_line: true)
          description      = sanitize_text(annotations[:description], MAX_DESCRIPTION_LENGTH).presence || summary
          reporter_email   = labels[:reporter_email].to_s.presence

          if status == 'resolved'
            resolve_incident(affected_service, alert_name)
            return nil
          end

          return nil unless status == 'firing'
          return nil unless Incident::AFFECTED_SERVICES.include?(affected_service)

          # Deduplicate: skip if an active incident for this service already
          # exists — unless the alert opts out with a `dedup=false` label, in
          # which case every firing alert opens its own incident.
          if labels[:dedup].to_s == 'false'
            if dedup_bypass_exhausted?(affected_service)
              Rails.logger.warn("Alert #{alert_name} skipped — dedup=false budget exhausted for #{affected_service}")
              return { skipped: true, reason: 'rate_limited' }
            end
          else
            existing = Incident.where(affected_service: affected_service)
                               .where(status: %w[open investigating])
                               .first
            if existing
              Rails.logger.info("Alert #{alert_name} skipped — incident #{existing.id} already open for #{affected_service}")
              return { skipped: true, incident_id: existing.id, reason: 'duplicate' }
            end
          end

          auto_investigate = AdminSettingsService.auto_investigate_enabled?

          incident = Incident.create!(
            title:            summary.presence || "#{alert_name}: #{affected_service} alert firing",
            description:      build_description(alert_name, description, labels, annotations),
            severity:         severity,
            status:           auto_investigate ? 'investigating' : 'open',
            affected_service: affected_service,
            reporter_id:      nil, # system-generated
          )

          session_result = nil
          if auto_investigate
            session_result = DevinSessionService.create_session(incident: incident)
          else
            Rails.logger.info("Auto-investigate disabled — skipping Devin session for incident #{incident.id}")
          end

          if session_result
            incident.update!(
              devin_session_id:     session_result[:session_id],
              devin_session_url:    session_result[:url],
              devin_session_status: 'running',
            )
          end

          SlackNotifierService.notify_incident(
            incident: incident,
            session_url: session_result&.dig(:url),
            reporter_email: reporter_email,
            alert_name: alert_name
          )

          Rails.logger.info("Incident #{incident.id} created from alert #{alert_name}, devin=#{session_result.present?}")

          { incident_id: incident.id, alert: alert_name, devin_session: session_result.present? }
        rescue ActiveRecord::RecordInvalid => e
          Rails.logger.error("Failed to create incident from alert #{alert_name}: #{e.message}")
          nil
        end

        # Only system-generated (alert-created) incidents are auto-resolved;
        # incidents a person reported stay open until a person closes them.
        def resolve_incident(affected_service, alert_name)
          return if affected_service.blank?

          incident = Incident.where(affected_service: affected_service, reporter_id: nil)
                             .where(status: %w[open investigating])
                             .first
          return unless incident

          incident.resolve!
          Rails.logger.info("Incident #{incident.id} auto-resolved by Grafana alert #{alert_name}")
        rescue Incident::InvalidTransitionError => e
          Rails.logger.warn("Could not auto-resolve incident #{incident.id} for alert #{alert_name}: #{e.message}")
        end

        def build_description(alert_name, base_description, labels, annotations)
          parts = [base_description]
          parts << "**Alert**: #{alert_name}" if alert_name.present?
          if (runbook = annotations[:runbook_url].to_s).present?
            parts << "**Runbook**: #{runbook}"
          end
          parts << "**Source**: Grafana Unified Alerting (auto-generated incident)"
          parts.join("\n\n")
        end

        def dedup_bypass_exhausted?(affected_service)
          limit = ENV.fetch('ALERT_DEDUP_BYPASS_LIMIT', DEFAULT_DEDUP_BYPASS_LIMIT).to_i
          limit = DEFAULT_DEDUP_BYPASS_LIMIT unless limit.positive?

          Incident.where(affected_service: affected_service, reporter_id: nil)
                  .where('created_at > ?', DEDUP_BYPASS_WINDOW.ago)
                  .count >= limit
        end

        # Alert text is attacker-influenced and ends up in the incident record
        # and the Devin triage prompt: strip control characters and bound it.
        def sanitize_text(value, max_length, single_line: false)
          text = value.to_s.gsub(/[^[:print:]\n\t]/, '')
          text = text.gsub(/\s+/, ' ') if single_line
          text.strip.truncate(max_length)
        end

        # Fails closed: without a configured, non-default secret the endpoint
        # rejects every request. Accepts either X-Alert-Secret or
        # Authorization: Bearer <secret> (Grafana webhook contact points).
        def verify_alert_secret
          expected = ENV.fetch('ALERT_WEBHOOK_SECRET', nil).to_s.strip
          if expected.empty? || RETIRED_SECRETS.include?(expected)
            Rails.logger.error('ALERT_WEBHOOK_SECRET is unset or a retired default; rejecting alert ingest')
            return render json: { error: 'Alert ingest is not configured' }, status: :service_unavailable
          end

          provided = request.headers['X-Alert-Secret'].presence ||
                     request.headers['Authorization'].to_s.delete_prefix('Bearer ').presence
          return if provided && ActiveSupport::SecurityUtils.secure_compare(provided, expected)

          render json: { error: 'Unauthorized' }, status: :unauthorized
        end
      end
    end
  end
end
