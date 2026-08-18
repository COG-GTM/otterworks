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

        # A `dedup=false` alert opens one incident (and one paid Devin session)
        # per occurrence. The chaos probe fires three uploads every five seconds
        # for the whole chaos window, so without a ceiling one trigger is a few
        # hundred sessions. The ceiling is well above what a demo does by hand.
        UNDEDUPED_WINDOW = 10.minutes
        UNDEDUPED_LIMIT  = 20

        # Matches the Incident model's own title validation.
        TITLE_LIMIT = 255
        ELLIPSIS = '…'.freeze

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

          processed = alerts.map { |alert| process_alert(alert) }.compact

          render json: { received: alerts.size, processed: processed.size, incidents: processed }
        end

        private

        # Titles carry a user-supplied filename and the model caps them at 255;
        # an over-long one would raise and leave the upload with no incident and
        # no triage session at all. The filename sits at the end and is what the
        # client matches an upload's incident on, so the front is dropped and
        # the whole tail kept.
        def incident_title(title)
          return title if title.length <= TITLE_LIMIT

          "#{ELLIPSIS}#{title.last(TITLE_LIMIT - ELLIPSIS.length)}"
        end

        def process_alert(alert)
          status           = alert[:status].to_s
          labels           = alert[:labels] || {}
          annotations      = alert[:annotations] || {}
          alert_name       = labels[:alertname].to_s
          affected_service = labels[:affected_service].to_s.presence || labels[:service].to_s.presence
          severity         = SEVERITY_MAP.fetch(labels[:severity].to_s, 'medium')
          summary          = annotations[:summary].to_s
          description      = annotations[:description].to_s.presence || summary

          if status == 'resolved'
            resolve_incident(affected_service, alert_name)
            return nil
          end

          return nil unless status == 'firing'
          return nil if affected_service.blank?

          # Deduplicate: skip if an active incident for this service already
          # exists — unless the alert opts out with a `dedup=false` label, in
          # which case every firing alert opens its own incident.
          if labels[:dedup].to_s == 'false'
            recent = Incident.where(affected_service: affected_service)
                             .where(created_at: UNDEDUPED_WINDOW.ago..)
                             .count
            if recent >= UNDEDUPED_LIMIT
              Rails.logger.warn("Alert #{alert_name} throttled — #{recent} incidents for #{affected_service} in the last #{UNDEDUPED_WINDOW.inspect}")
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
            title:            incident_title(summary.presence || "#{alert_name}: #{affected_service} alert firing"),
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
          elsif auto_investigate && DevinSessionService.configured?
            # Record the miss: without it the incident is indistinguishable
            # from one whose session is still being created, and a broken
            # credential looks like slowness for as long as nobody checks.
            incident.update(devin_session_status: 'failed')
          end

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

        def verify_alert_secret
          expected = ENV.fetch('ALERT_WEBHOOK_SECRET', nil)
          return if expected.nil? # not configured → allow (dev/test)

          # Accept either X-Alert-Secret header or Authorization: Bearer <secret>
          # (Grafana webhook contact points send the token as a Bearer header)
          provided = request.headers['X-Alert-Secret'].presence ||
                     request.headers['Authorization'].to_s.delete_prefix('Bearer ').presence
          return if provided == expected

          render json: { error: 'Unauthorized' }, status: :unauthorized
        end
      end
    end
  end
end
