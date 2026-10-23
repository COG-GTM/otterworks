module Api
  module V1
    module Admin
      class QuotasController < ApplicationController
        before_action :require_admin!, only: %i[update]
        before_action :require_quota_owner_or_admin!, only: %i[show]
        before_action :set_quota, only: %i[show update]

        # GET /api/v1/admin/quotas/:user_id
        def show
          render json: @quota, serializer: StorageQuotaSerializer
        end

        # PUT /api/v1/admin/quotas/:user_id
        def update
          previous_attributes = @quota.attributes.slice('quota_bytes', 'tier')

          if @quota.update(quota_params)
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

        # Users may read their own quota; anyone else's requires an admin role.
        def require_quota_owner_or_admin!
          return if admin_role?
          return if current_user_id.present? && current_user_id.to_s == params[:user_id].to_s

          render json: { error: 'Admin role required' }, status: :forbidden
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
