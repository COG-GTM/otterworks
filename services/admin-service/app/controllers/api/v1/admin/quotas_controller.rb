module Api
  module V1
    module Admin
      class QuotasController < ApplicationController
        before_action :set_quota, only: %i[show update]

        # GET /api/v1/admin/quotas/:user_id
        def show
          authorize @quota
          render json: @quota, serializer: StorageQuotaSerializer
        end

        # PATCH/PUT /api/v1/admin/quotas/:user_id
        def update
          authorize @quota
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

        # auth-service owns users.quota_bytes; push updates so file-service
        # enforcement sees the new limit.
        def sync_quota_to_auth_service
          return unless @quota.saved_change_to_quota_bytes?

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
