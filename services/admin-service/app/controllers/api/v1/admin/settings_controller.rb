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
          render json: DevinSessionService.credentials_status
        end

        # DELETE /api/v1/admin/settings/devin_credentials
        # Clears the stored pair. Env-supplied credentials take precedence and
        # are not revocable here, so the returned status still reports
        # `configured` wherever DEVIN_API_KEY/DEVIN_ORG_ID are both set.
        def destroy_devin_credentials
          AdminSettingsService.clear_devin_credentials
          Rails.logger.info('Devin credentials cleared via settings API')
          audit('settings.devin_credentials_cleared', {})
          render json: DevinSessionService.credentials_status
        rescue StandardError => e
          # The clear is only complete once the leftover cache copy is gone;
          # reporting success otherwise invites the pair to come back.
          Rails.logger.error("Failed to clear Devin credentials: #{e.message}")
          render json: { error: 'Could not fully clear the credentials; retry', detail: e.message },
                 status: :service_unavailable
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
      end
    end
  end
end
