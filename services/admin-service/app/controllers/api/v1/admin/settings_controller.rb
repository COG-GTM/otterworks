module Api
  module V1
    module Admin
      class SettingsController < ApplicationController
        # An org id ends up in the path of an outbound Devin API call whose
        # status comes back to the caller, so it is constrained to what an id
        # can contain rather than merely escaped.
        ORG_ID_FORMAT = /\A[A-Za-z0-9._-]{1,128}\z/

        # Reads only report presence/toggles; writes change the credentials and
        # webhook the service itself uses, so they are restricted to admins.
        before_action :require_admin!, only: %i[
          update_auto_investigate
          update_devin_credentials destroy_devin_credentials
          update_slack_notifications destroy_slack_notifications
        ]

        # GET /api/v1/admin/settings/auto_investigate
        def auto_investigate
          render json: { enabled: AdminSettingsService.auto_investigate_enabled? }
        end

        # PUT /api/v1/admin/settings/auto_investigate
        def update_auto_investigate
          enabled = ActiveModel::Type::Boolean.new.cast(params[:enabled])
          if enabled.nil?
            return render json: { error: 'Missing required parameter: enabled' }, status: :bad_request
          end
          AdminSettingsService.set_auto_investigate(enabled)
          Rails.logger.info("Auto-investigate toggled to #{enabled}")
          render json: { enabled: AdminSettingsService.auto_investigate_enabled? }
        end

        # GET /api/v1/admin/settings/devin_credentials[?verify=true]
        # Reports presence only — credential values are never returned. Uses the
        # same resolution as session creation; `verify=true` additionally calls
        # the Devin API, because a key that is present but not authorized for
        # the organization reads as "configured" while creating no sessions.
        def devin_credentials
          verify = ActiveModel::Type::Boolean.new.cast(params[:verify]) || false
          render json: DevinSessionService.credentials_status(verify: verify)
        end

        # PUT /api/v1/admin/settings/devin_credentials
        def update_devin_credentials
          api_key = params[:api_key].to_s.strip
          org_id  = params[:org_id].to_s.strip
          if api_key.empty? || org_id.empty?
            return render json: { error: 'Missing required parameters: api_key, org_id' }, status: :bad_request
          end
          unless org_id.match?(ORG_ID_FORMAT)
            return render json: { error: 'Invalid org_id' }, status: :bad_request
          end

          # Reject a pair the Devin API will not accept rather than storing it
          # and discovering at the next incident that no session was created.
          # `force=true` stores it anyway (e.g. when the API is unreachable).
          unless ActiveModel::Type::Boolean.new.cast(params[:force])
            check = DevinSessionService.verify_credentials(api_key: api_key, org_id: org_id)
            unless check[:valid]
              Rails.logger.warn("Rejected Devin credentials: #{check[:error]}")
              # A transient outage is not a bad key: 503 tells the operator to
              # retry (or pass force=true) instead of hunting for a new key.
              return render json: {
                error: check[:unreachable] ? 'Could not reach the Devin API to verify; retry or send force=true' : 'Credentials rejected by the Devin API',
                detail: check[:error]
              }, status: check[:unreachable] ? :service_unavailable : :unprocessable_entity
            end
          end

          AdminSettingsService.set_devin_credentials(api_key: api_key, org_id: org_id)
          Rails.logger.info('Devin credentials updated via settings API')
          audit('settings.devin_credentials_updated', org_id: org_id, api_key: '********')
          status = DevinSessionService.credentials_status
          # env and Secrets Manager both win over the stored pair, so on such a
          # tenant the status describes a pair the operator did not just write
          # and the new one will never be used. Say so rather than looking like
          # a successful change.
          if status[:source] && status[:source] != 'settings'
            Rails.logger.warn("Stored Devin credentials are shadowed by #{status[:source]}")
            status = status.merge(stored_pair_shadowed_by: status[:source])
          end
          render json: status
        end

        # DELETE /api/v1/admin/settings/devin_credentials
        # Clears the stored pair. Only that pair: env vars and a Secrets Manager
        # secret take precedence and are not revocable here, so the returned
        # status still reports `configured` on a tenant wired to either — revoke
        # those at their source.
        def destroy_devin_credentials
          begin
            cache_cleared = AdminSettingsService.clear_devin_credentials
          rescue StandardError => e
            # Only the revoke itself can fail here; anything after it has
            # already been made durable and must not report a retry.
            Rails.logger.error("Failed to clear Devin credentials: #{e.message}")
            return render json: { error: 'Could not clear the credentials; retry' }, status: :service_unavailable
          end

          Rails.logger.info("Devin credentials cleared via settings API (cache_cleared=#{cache_cleared})")
          audit('settings.devin_credentials_cleared', cache_cleared: cache_cleared)
          # The revoke is already durable; the flag only says whether the
          # leftover cache copy could be deleted too. Re-resolving credentials
          # for the status touches Secrets Manager and Postgres, and a failure
          # there must not surface as "the revoke did not happen".
          status = begin
            DevinSessionService.credentials_status
          rescue StandardError => e
            Rails.logger.error("Devin credentials cleared, but the status read failed: #{e.message}")
            # Keep the response shape stable; nil says "could not tell", which
            # is not the same answer as "not configured".
            { api_key_configured: nil, org_id_configured: nil, status_unavailable: true }
          end
          render json: status.merge(legacy_cache_cleared: cache_cleared)
        end

        # GET /api/v1/admin/settings/slack_notifications
        # Reports the toggle plus webhook presence — the URL itself is never
        # returned.
        def slack_notifications
          render json: slack_status
        end

        # PUT /api/v1/admin/settings/slack_notifications
        # Accepts `enabled`, `webhook_url` and/or `bot_token` — at least one is
        # required.
        def update_slack_notifications
          enabled = params.key?(:enabled) ? ActiveModel::Type::Boolean.new.cast(params[:enabled]) : nil
          webhook_url = params[:webhook_url].to_s.strip
          bot_token = params[:bot_token].to_s.strip

          if enabled.nil? && webhook_url.empty? && bot_token.empty?
            return render json: { error: 'Provide at least one of: enabled, webhook_url, bot_token' },
                          status: :bad_request
          end

          unless bot_token.empty? || valid_slack_bot_token?(bot_token)
            return render json: { error: 'bot_token must be a Slack bot token (xoxb-...)' }, status: :bad_request
          end

          unless webhook_url.empty? || valid_slack_webhook_url?(webhook_url)
            return render json: { error: 'webhook_url must be an https://hooks.slack.com/ URL' },
                          status: :bad_request
          end

          AdminSettingsService.set_slack_notifications(enabled) unless enabled.nil?
          AdminSettingsService.set_slack_webhook_url(webhook_url) unless webhook_url.empty?
          AdminSettingsService.set_slack_bot_token(bot_token) unless bot_token.empty?
          Rails.logger.info('Slack notification settings updated via settings API')
          render json: slack_status
        end

        # DELETE /api/v1/admin/settings/slack_notifications
        # Clears the stored webhook URL and bot token. Env-supplied
        # SLACK_WEBHOOK_URL / SLACK_BOT_TOKEN take precedence and are not
        # revocable here.
        def destroy_slack_notifications
          AdminSettingsService.clear_slack_credentials
          Rails.logger.info('Slack webhook URL and bot token cleared via settings API')
          render json: slack_status
        end

        private

        def audit(action, changes_made)
          AuditLogger.log(
            action: action,
            resource_type: 'DevinCredentials',
            request: request,
            changes_made: changes_made
          )
        end

        def valid_slack_webhook_url?(url)
          uri = URI.parse(url)
          uri.scheme == 'https' && uri.host.to_s.downcase == 'hooks.slack.com' && uri.userinfo.nil?
        rescue URI::Error
          false
        end

        def valid_slack_bot_token?(token)
          SlackNotifierService.valid_bot_token?(token)
        end

        def slack_status
          {
            enabled: AdminSettingsService.slack_notifications_enabled?,
            webhook_configured: ENV.fetch('SLACK_WEBHOOK_URL', nil).present? ||
              AdminSettingsService.slack_webhook_url.present?,
            # A stored token only counts as configured if the sender would
            # actually use it (see SlackNotifierService#stored_bot_token).
            bot_token_configured: ENV.fetch('SLACK_BOT_TOKEN', nil).present? ||
              SlackNotifierService.valid_bot_token?(AdminSettingsService.slack_bot_token)
          }
        end
      end
    end
  end
end
