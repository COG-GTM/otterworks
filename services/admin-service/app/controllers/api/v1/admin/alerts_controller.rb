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

        SEVERITY_MAP = {
          'critical' => 'critical',
          'high'     => 'high',
          'warning'  => 'medium',
          'info'     => 'low',
        }.freeze

        # Grafana groups alerts per notification; real senders stay well below this.
        MAX_ALERTS_PER_REQUEST = 10

        # POST /api/v1/admin/alerts/ingest
        def ingest
          alerts = params[:alerts]
          unless alerts.is_a?(Array)
            return render json: { error: 'Missing alerts array' }, status: :bad_request
          end

          if alerts.size > MAX_ALERTS_PER_REQUEST
            return render json: { error: "Too many alerts (max #{MAX_ALERTS_PER_REQUEST} per request)" },
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
          summary          = annotations[:summary].to_s
          description      = annotations[:description].to_s.presence || summary
          # Routing hints that open extra incidents or @-mention people are only
          # honoured from senders that authenticated with ALERT_WEBHOOK_SECRET.
          reporter_email   = trusted_sender? ? labels[:reporter_email].to_s.presence : nil

          if status == 'resolved'
            resolve_incident(affected_service, alert_name)
            return nil
          end

          return nil unless status == 'firing'
          return nil if affected_service.blank?

          # Deduplicate: skip if an active incident for this service already
          # exists — unless a trusted sender opts out with a `dedup=false` label
          # and the service is still within its incident budget.
          unless bypass_dedup?(labels, affected_service)
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
          if auto_investigate && AlertBudget.devin_session_allowed?(affected_service)
            session_result = DevinSessionService.create_session(incident: incident)
          elsif auto_investigate
            Rails.logger.warn("Devin session budget exhausted for #{affected_service} — " \
                              "skipping Devin session for incident #{incident.id}")
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

        def bypass_dedup?(labels, affected_service)
          return false unless labels[:dedup].to_s == 'false'
          return false unless trusted_sender?

          return true if AlertBudget.dedup_bypass_allowed?(affected_service)

          Rails.logger.warn("Incident budget exhausted for #{affected_service} — ignoring dedup=false")
          false
        end

        # True only when ALERT_WEBHOOK_SECRET is configured and the request
        # presented it; unauthenticated (dev-mode) ingest is never trusted.
        def trusted_sender?
          @trusted_sender
        end

        def verify_alert_secret
          @trusted_sender = false
          expected = ENV.fetch('ALERT_WEBHOOK_SECRET', nil)
          return if expected.nil? # not configured → allow, but untrusted (dev/test)

          # Accept either X-Alert-Secret header or Authorization: Bearer <secret>
          # (Grafana webhook contact points send the token as a Bearer header)
          provided = request.headers['X-Alert-Secret'].presence ||
                     request.headers['Authorization'].to_s.delete_prefix('Bearer ').presence
          if provided && ActiveSupport::SecurityUtils.secure_compare(provided, expected)
            @trusted_sender = true
            return
          end

          render json: { error: 'Unauthorized' }, status: :unauthorized
        end
      end
    end
  end
end
