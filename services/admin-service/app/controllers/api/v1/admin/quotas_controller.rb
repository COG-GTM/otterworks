module Api
  module V1
    module Admin
      class QuotasController < ApplicationController
        # Authorize before the lookup so non-admins always get 403 and
        # cannot probe which users have quota records.
        before_action :authorize_quota_access
        before_action :set_quota, only: %i[show update]

        # GET /api/v1/admin/quotas/:user_id
        def show
          render json: @quota, serializer: StorageQuotaSerializer
        end

        # PATCH/PUT /api/v1/admin/quotas/:user_id
        def update
          previous_attributes = @quota.attributes.slice('quota_bytes', 'tier')

          if @quota.update(quota_params)
            sync_quota_to_auth_service
            AuditLogger.log(
              action: 'quota.updated',
              resource_type: 'StorageQuota',
              resource_id: @quota.id,
              request: request,
              changes_made: { before: previous_attributes, after: @quota.attributes.slice('quota_bytes', 'tier') }
            )
            render json: @quota, serializer: StorageQuotaSerializer
          else
            render json: { error: 'Validation failed', details: @quota.errors.full_messages },
                   status: :unprocessable_entity
          end
        end

        private

        def authorize_quota_access
          authorize StorageQuota, policy_class: StorageQuotaPolicy
        end

        # auth-service owns users.quota_bytes; push updates so file-service
        # enforcement sees the new limit. Syncs whenever a quota_bytes value
        # was submitted (not only when it changed locally) so a re-submitted
        # value can repair a previously failed push.
        def sync_quota_to_auth_service
          return if quota_params[:quota_bytes].blank?

          AuthServiceClient.update_quota(
            user_id: @quota.user_id,
            quota_bytes: @quota.quota_bytes,
            authorization: request.headers['Authorization']
          )
        end

        def set_quota
          @quota = StorageQuota.find_by!(user_id: params[:user_id])
        end

        def quota_params
          params.require(:quota).permit(:quota_bytes, :tier)
        end
      end
    end
  end
end
