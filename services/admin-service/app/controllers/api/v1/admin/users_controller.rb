module Api
  module V1
    module Admin
      class UsersController < ApplicationController
        # Granting roles is the one operation that can widen someone's
        # privileges, so it stays with the top roles rather than every admin.
        ROLE_GRANTING_ROLES = %w[super_admin owner].freeze

        # User listings expose emails/roles/quotas, so reads are guarded too
        # (the api-gateway flow test expects non-admins to get 403 here).
        before_action :require_admin!
        before_action :set_user, only: %i[show update destroy suspend activate]

        # GET /api/v1/admin/users
        def index
          scope = AdminUser.includes(:storage_quota)
          scope = scope.search(params[:q]) if params[:q].present?
          scope = scope.by_role(params[:role]) if params[:role].present?
          scope = scope.where(status: params[:status]) if params[:status].present?
          scope = scope.order(created_at: :desc)

          result = paginate(scope)

          render json: {
            users: ActiveModelSerializers::SerializableResource.new(result[:records], include_quota: true),
            total: result[:total],
            page: result[:page],
            per_page: result[:per_page]
          }
        end

        # GET /api/v1/admin/users/:id
        def show
          render json: @user, serializer: AdminUserSerializer, include_quota: true
        end

        # PUT /api/v1/admin/users/:id
        def update
          previous_attributes = @user.attributes.slice('role', 'display_name', 'email')

          if @user.update(user_params)
            AuditLogger.log(
              action: 'user.updated',
              resource_type: 'AdminUser',
              resource_id: @user.id,
              request: request,
              changes_made: { before: previous_attributes,
                              after: @user.attributes.slice('role', 'display_name', 'email') }
            )
            render json: @user, serializer: AdminUserSerializer, include_quota: true
          else
            render json: { error: 'Validation failed', details: @user.errors.full_messages },
                   status: :unprocessable_entity
          end
        end

        # DELETE /api/v1/admin/users/:id
        def destroy
          @user.soft_delete!

          AuditLogger.log(
            action: 'user.deleted',
            resource_type: 'AdminUser',
            resource_id: @user.id,
            request: request
          )

          head :no_content
        end

        # PUT /api/v1/admin/users/:id/suspend
        def suspend
          @user.suspend!(reason: params[:reason])

          AuditLogger.log(
            action: 'user.suspended',
            resource_type: 'AdminUser',
            resource_id: @user.id,
            request: request,
            changes_made: { reason: params[:reason] }
          )

          render json: @user, serializer: AdminUserSerializer, include_quota: true
        end

        # PUT /api/v1/admin/users/:id/activate
        def activate
          @user.activate!

          AuditLogger.log(
            action: 'user.activated',
            resource_type: 'AdminUser',
            resource_id: @user.id,
            request: request
          )

          render json: @user, serializer: AdminUserSerializer, include_quota: true
        end

        private

        def set_user
          @user = AdminUser.includes(:storage_quota).find(params[:id]) # nosemgrep: ruby.rails.security.brakeman.check-unscoped-find.check-unscoped-find
        end

        # `role` is the privilege boundary itself, so it is never mass-assignable:
        # it is added to the permitted set only after an explicit check that the
        # caller holds a role allowed to grant roles.
        def user_params
          permitted = %i[email display_name avatar_url]
          permitted << :role if role_assignable?
          params.require(:user).permit(*permitted) # nosemgrep: ruby.lang.security.model-attr-accessible.model-attr-accessible
        end

        def role_assignable?
          ROLE_GRANTING_ROLES.include?(current_user_role)
        end
      end
    end
  end
end
