module Api
  module V1
    module Admin
      class SettingsController < ApplicationController
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

        # GET /api/v1/admin/settings/devin_credentials
        # Reports presence only — credential values are never returned. Uses the
        # same resolution as session creation, so a "configured" answer here
        # means sessions will actually be created.
        def devin_credentials
          render json: DevinSessionService.credentials_status
        end

        # PUT /api/v1/admin/settings/devin_credentials
        def update_devin_credentials
          api_key = params[:api_key].to_s.strip
          org_id  = params[:org_id].to_s.strip
          if api_key.empty? || org_id.empty?
            return render json: { error: 'Missing required parameters: api_key, org_id' }, status: :bad_request
          end

          AdminSettingsService.set_devin_credentials(api_key: api_key, org_id: org_id)
          Rails.logger.info('Devin credentials updated via settings API')
          render json: DevinSessionService.credentials_status
        end

        # DELETE /api/v1/admin/settings/devin_credentials
        # Clears the stored pair. Env-supplied credentials take precedence and
        # are not revocable here, so the returned status still reports
        # `configured` wherever DEVIN_API_KEY/DEVIN_ORG_ID are both set.
        def destroy_devin_credentials
          AdminSettingsService.clear_devin_credentials
          Rails.logger.info('Devin credentials cleared via settings API')
          render json: DevinSessionService.credentials_status
        end

        # GET /api/v1/admin/settings/slack_notifications
        # Reports the toggle plus webhook presence — the URL itself is never
        # returned.
        def slack_notifications
          render json: slack_status
        end

        # PUT /api/v1/admin/settings/slack_notifications
        # Accepts `enabled` and/or `webhook_url` — at least one is required.
        def update_slack_notifications
          enabled = params.key?(:enabled) ? ActiveModel::Type::Boolean.new.cast(params[:enabled]) : nil
          webhook_url = params[:webhook_url].to_s.strip

          if enabled.nil? && webhook_url.empty?
            return render json: { error: 'Provide at least one of: enabled, webhook_url' }, status: :bad_request
          end

          unless webhook_url.empty? || webhook_url.start_with?('https://hooks.slack.com/')
            return render json: { error: 'webhook_url must be an https://hooks.slack.com/ URL' },
                          status: :bad_request
          end

          AdminSettingsService.set_slack_notifications(enabled) unless enabled.nil?
          AdminSettingsService.set_slack_webhook_url(webhook_url) unless webhook_url.empty?
          Rails.logger.info('Slack notification settings updated via settings API')
          render json: slack_status
        end

        # DELETE /api/v1/admin/settings/slack_notifications
        # Clears the stored webhook URL. An env-supplied SLACK_WEBHOOK_URL
        # takes precedence and is not revocable here.
        def destroy_slack_notifications
          AdminSettingsService.clear_slack_webhook_url
          Rails.logger.info('Slack webhook URL cleared via settings API')
          render json: slack_status
        end

        private

        def slack_status
          {
            enabled: AdminSettingsService.slack_notifications_enabled?,
            webhook_configured: ENV.fetch('SLACK_WEBHOOK_URL', nil).present? ||
              AdminSettingsService.slack_webhook_url.present?
          }
        end
      end
    end
  end
end
