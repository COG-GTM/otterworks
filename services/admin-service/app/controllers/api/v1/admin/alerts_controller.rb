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

        # Grafana groups at most a handful of alerts per notification; anything
        # larger is a flood, not a real alert group.
        MAX_ALERTS_PER_REQUEST = 50
        MAX_TITLE_LENGTH       = 255
        MAX_DESCRIPTION_LENGTH = 4_000

        # Publicly known values that once shipped as defaults; never accepted.
        RETIRED_SECRETS = %w[demo-alert-secret].freeze

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
          alert_name       = labels[:alertname].to_s
          affected_service = labels[:affected_service].to_s.presence || labels[:service].to_s.presence
          severity         = SEVERITY_MAP.fetch(labels[:severity].to_s, 'medium')
          summary          = annotations[:summary].to_s.truncate(MAX_TITLE_LENGTH)
          description      = (annotations[:description].to_s.presence || summary).truncate(MAX_DESCRIPTION_LENGTH)
          reporter_email   = labels[:reporter_email].to_s.presence

          if status == 'resolved'
            resolve_incident(affected_service, alert_name)
            return nil
          end

          return nil unless status == 'firing'
          return nil if affected_service.blank?

          # Deduplicate: skip if an active incident for this service already
          # exists — unless the alert opts out with a `dedup=false` label, in
          # which case every firing alert opens its own incident, up to a
          # per-service hourly budget. Past the budget it dedupes as usual.
          bypass_dedup = labels[:dedup].to_s == 'false' &&
                         AlertIngestBudget.allow_dedup_bypass?(affected_service)
          unless bypass_dedup
            existing = Incident.where(affected_service: affected_service)
                               .where(status: %w[open investigating])
                               .first
            if existing
              Rails.logger.info("Alert #{alert_name} skipped — incident #{existing.id} already open for #{affected_service}")
              return { skipped: true, incident_id: existing.id, reason: 'duplicate' }
            end
          end

          auto_investigate = AdminSettingsService.auto_investigate_enabled?

          incident_description = build_description(alert_name, description, labels, annotations)
                                 .truncate(MAX_DESCRIPTION_LENGTH)

          incident = Incident.create!(
            title:            (summary.presence || "#{alert_name}: #{affected_service} alert firing").truncate(MAX_TITLE_LENGTH),
            description:      incident_description,
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

        def resolve_incident(affected_service, alert_name)
          return if affected_service.blank?

          incident = Incident.where(affected_service: affected_service)
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

        # The ingest path skips JWT auth (JwtAuthenticator::EXCLUDED_PATHS), so
        # this shared secret is its only gate: fail closed when it is missing
        # or still a publicly known default.
        def verify_alert_secret
          expected = ENV.fetch('ALERT_WEBHOOK_SECRET', nil).to_s.strip
          if expected.empty? || RETIRED_SECRETS.include?(expected)
            Rails.logger.error('ALERT_WEBHOOK_SECRET is unset or a retired default; rejecting alert ingest')
            return render json: { error: 'Alert ingest is not configured' }, status: :service_unavailable
          end

          # Accept either X-Alert-Secret header or Authorization: Bearer <secret>
          # (Grafana webhook contact points send the token as a Bearer header)
          provided = request.headers['X-Alert-Secret'].presence || bearer_token
          return if provided && ActiveSupport::SecurityUtils.secure_compare(provided, expected)

          render json: { error: 'Unauthorized' }, status: :unauthorized
        end

        def bearer_token
          scheme, token = request.headers['Authorization'].to_s.split(' ', 2)
          token.presence if scheme&.casecmp?('Bearer')
        end
      end
    end
  end
end
