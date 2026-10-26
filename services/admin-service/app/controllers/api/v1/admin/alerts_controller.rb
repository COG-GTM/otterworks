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

        # Every alert-created incident can start a paid Devin session and page
        # Slack, and the failures behind some alerts are user-triggered, so
        # incident creation is capped per affected service in a rolling window
        # (on top of the one-open-incident dedup), including for `dedup=false`.
        DEFAULT_INCIDENT_RATE_LIMIT = 5
        DEFAULT_INCIDENT_RATE_WINDOW_SECONDS = 3600

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

        def process_alert(alert)
          status           = alert[:status].to_s
          labels           = alert[:labels] || {}
          annotations      = alert[:annotations] || {}
          alert_name       = labels[:alertname].to_s
          affected_service = labels[:affected_service].to_s.presence || labels[:service].to_s.presence
          severity         = SEVERITY_MAP.fetch(labels[:severity].to_s, 'medium')
          summary          = annotations[:summary].to_s
          description      = annotations[:description].to_s.presence || summary
          reporter_email   = labels[:reporter_email].to_s.presence

          if status == 'resolved'
            resolve_incident(affected_service, alert_name)
            return nil
          end

          return nil unless status == 'firing'
          return nil if affected_service.blank?

          auto_investigate = AdminSettingsService.auto_investigate_enabled?

          admission = admit_incident(alert_name, affected_service, labels) do
            Incident.create!(
              title:            summary.presence || "#{alert_name}: #{affected_service} alert firing",
              description:      build_description(alert_name, description, labels, annotations),
              severity:         severity,
              status:           auto_investigate ? 'investigating' : 'open',
              affected_service: affected_service,
              reporter_id:      nil, # system-generated
            )
          end
          return admission unless admission.is_a?(Incident)

          incident = admission

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

        # Runs the dedup and rate-cap checks and, if both pass, yields to create
        # the incident. A per-service advisory lock serialises concurrent alerts
        # so a burst cannot race past either check. Returns the created
        # Incident, or a skip result hash.
        def admit_incident(alert_name, affected_service, labels)
          Incident.transaction do
            Incident.connection.execute(
              Incident.sanitize_sql_array(
                ['SELECT pg_advisory_xact_lock(hashtext(?))', "alert-incident:#{affected_service}"]
              )
            )

            # Deduplicate onto an active incident for this service unless the
            # alert opts out with a `dedup=false` label.
            if labels[:dedup].to_s != 'false'
              existing = Incident.active.where(affected_service: affected_service).first
              if existing
                Rails.logger.info("Alert #{alert_name} skipped — incident #{existing.id} already open for #{affected_service}")
                next { skipped: true, incident_id: existing.id, reason: 'duplicate' }
              end
            end

            capped = incident_rate_limited(alert_name, affected_service)
            next capped if capped

            yield
          end
        end

        def incident_rate_limited(alert_name, affected_service)
          recent = Incident.where(affected_service: affected_service, reporter_id: nil)
                           .where('created_at > ?', incident_rate_window.seconds.ago)
          return if recent.count < incident_rate_limit

          Rails.logger.warn(
            "Alert #{alert_name} skipped — #{affected_service} reached #{incident_rate_limit} " \
            "alert-created incidents in #{incident_rate_window}s"
          )
          { skipped: true, incident_id: recent.order(created_at: :desc).pick(:id), reason: 'rate_limited' }
        end

        def incident_rate_limit
          positive_env_int('ALERT_INCIDENT_RATE_LIMIT', DEFAULT_INCIDENT_RATE_LIMIT)
        end

        def incident_rate_window
          positive_env_int('ALERT_INCIDENT_RATE_WINDOW_SECONDS', DEFAULT_INCIDENT_RATE_WINDOW_SECONDS)
        end

        def positive_env_int(name, default)
          value = Integer(ENV.fetch(name, default), exception: false)
          value&.positive? ? value : default
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
