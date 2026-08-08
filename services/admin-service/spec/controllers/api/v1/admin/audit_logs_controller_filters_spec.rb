require 'rails_helper'

# Complements spec/controllers/api/v1/admin/audit_logs_controller_spec.rb with the
# time-range filters and their date parsing errors.
RSpec.describe Api::V1::Admin::AuditLogsController do
  before { set_jwt_env(request) }

  describe 'GET #index with time filters' do
    let!(:old_log) { create(:audit_log, created_at: 10.days.ago) }
    let!(:recent_log) { create(:audit_log, created_at: 1.hour.ago) }

    def body_ids
      JSON.parse(response.body)['audit_logs'].map { |log| log['id'] }
    end

    it 'filters with since' do
      get :index, params: { since: 2.days.ago.iso8601 }

      expect(response).to have_http_status(:ok)
      expect(body_ids).to eq([recent_log.id])
    end

    it 'filters with until' do
      get :index, params: { until: 2.days.ago.iso8601 }

      expect(body_ids).to eq([old_log.id])
    end

    it 'combines both bounds' do
      get :index, params: { since: 11.days.ago.iso8601, until: 2.days.ago.iso8601 }

      expect(body_ids).to eq([old_log.id])
    end

    it 'filters by actor' do
      actor_id = SecureRandom.uuid
      mine = create(:audit_log, actor_id: actor_id)

      get :index, params: { actor_id: actor_id }

      expect(body_ids).to eq([mine.id])
    end

    it 'filters by resource type and id together' do
      resource_id = SecureRandom.uuid
      match = create(:audit_log, resource_type: 'FeatureFlag', resource_id: resource_id)
      create(:audit_log, resource_type: 'FeatureFlag')

      get :index, params: { resource_type: 'FeatureFlag', resource_id: resource_id }

      expect(body_ids).to eq([match.id])
    end

    it 'returns 400 for an unparseable since value' do
      get :index, params: { since: 'yesterday-ish' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Invalid date format: yesterday-ish')
    end

    it 'returns 400 for an out-of-range until value' do
      get :index, params: { until: '2024-13-45' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Invalid date format: 2024-13-45')
    end
  end
end
