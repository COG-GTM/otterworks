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
      end
    end
  end
end
