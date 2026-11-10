module Api
  module V1
    module Admin
      class SharingPoliciesController < ApplicationController
        before_action :require_admin!, only: %i[update]

        # GET /api/v1/admin/sharing_policy
        def show
          render json: SharingPolicy.for_workspace.to_policy
        end

        # PUT /api/v1/admin/sharing_policy
        # Only links created after the change read the new values; existing links keep their expires_at.
        def update
          changes = policy_params
          if changes.empty?
            return render json: { error: 'Validation failed', details: ['No sharing policy fields provided'] },
                          status: :unprocessable_entity
          end

          policy = nil
          SharingPolicy.transaction do
            # ON CONFLICT DO NOTHING makes concurrent first updates serialize on the row lock below
            # instead of racing on the unique workspace_id index.
            SharingPolicy.insert_all([{ workspace_id: SharingPolicy::DEFAULT_WORKSPACE_ID }], unique_by: :workspace_id)
            policy = SharingPolicy.lock.find_by!(workspace_id: SharingPolicy::DEFAULT_WORKSPACE_ID)
            before = policy.to_policy
            policy.assign_attributes(changes)
            raise ActiveRecord::Rollback unless policy.valid?
            next if policy.to_policy == before

            policy.updated_by = current_user_id
            policy.save!
            record_audit!(policy, before)
          end

          if policy.errors.any?
            render json: { error: 'Validation failed', details: policy.errors.full_messages },
                   status: :unprocessable_entity
          else
            render json: policy.to_policy
          end
        end

        private

        def policy_params
          params.permit(*SharingPolicy::POLICY_FIELDS).to_h
        end

        def record_audit!(policy, before)
          AuditLog.record!(
            action: 'sharing_policy.updated',
            resource_type: 'SharingPolicy',
            resource_id: policy.id,
            actor_id: current_user_id,
            actor_email: current_user_email,
            changes_made: { workspace_id: policy.workspace_id, before: before, after: policy.to_policy },
            ip_address: request.remote_ip,
            user_agent: request.user_agent
          )
        end
      end
    end
  end
end
