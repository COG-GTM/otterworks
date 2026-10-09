module Api
  module V1
    module Admin
      class AnnouncementsController < ApplicationController
        before_action :require_admin!, only: %i[create update destroy]
        before_action :set_announcement, only: %i[show update destroy]

        # GET /api/v1/admin/announcements
        def index
          scope = readable_announcements
          scope = scope.where(status: params[:status]) if admin? && params[:status].present?
          scope = scope.by_severity(params[:severity]) if params[:severity].present?
          scope = scope.active if params[:active] == 'true'
          scope = scope.order(created_at: :desc)

          result = paginate(scope)

          render json: {
            announcements: ActiveModelSerializers::SerializableResource.new(result[:records]),
            total: result[:total],
            page: result[:page],
            per_page: result[:per_page]
          }
        end

        # GET /api/v1/admin/announcements/:id
        def show
          render json: @announcement, serializer: AnnouncementSerializer
        end

        # POST /api/v1/admin/announcements
        def create
          announcement = Announcement.new(announcement_params)
          announcement.created_by = current_user_id

          if announcement.save
            AuditLogger.log(
              action: 'announcement.created',
              resource_type: 'Announcement',
              resource_id: announcement.id,
              request: request,
              changes_made: announcement.attributes
            )
            render json: announcement, serializer: AnnouncementSerializer, status: :created
          else
            render json: { error: 'Validation failed', details: announcement.errors.full_messages },
                   status: :unprocessable_entity
          end
        end

        # PUT /api/v1/admin/announcements/:id
        def update
          previous_attributes = @announcement.attributes

          if @announcement.update(announcement_params)
            AuditLogger.log(
              action: 'announcement.updated',
              resource_type: 'Announcement',
              resource_id: @announcement.id,
              request: request,
              changes_made: { before: previous_attributes, after: @announcement.attributes }
            )
            render json: @announcement, serializer: AnnouncementSerializer
          else
            render json: { error: 'Validation failed', details: @announcement.errors.full_messages },
                   status: :unprocessable_entity
          end
        end

        # DELETE /api/v1/admin/announcements/:id
        def destroy
          @announcement.destroy!

          AuditLogger.log(
            action: 'announcement.deleted',
            resource_type: 'Announcement',
            resource_id: @announcement.id,
            request: request
          )

          head :no_content
        end

        private

        def set_announcement
          @announcement = readable_announcements.find(params[:id])
        end

        # Non-admins only see published, in-window announcements targeted at their role.
        def readable_announcements
          admin? ? Announcement.all : Announcement.active.for_role(current_user_role)
        end

        def announcement_params
          params.require(:announcement).permit(:title, :body, :severity, :status, :starts_at, :ends_at,
                                               target_audience: {})
        end
      end
    end
  end
end
