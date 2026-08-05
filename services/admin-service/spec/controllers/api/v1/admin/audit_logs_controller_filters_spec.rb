require 'rails_helper'

RSpec.describe Api::V1::Admin::AuditLogsController do
  before { set_jwt_env(request) }

  describe 'GET #index time filters' do
    let!(:old_log) { create(:audit_log, created_at: 10.days.ago) }
    let!(:recent_log) { create(:audit_log, created_at: 1.hour.ago) }

    it 'filters entries newer than :since' do
      get :index, params: { since: 2.days.ago.iso8601 }

      ids = JSON.parse(response.body)['audit_logs'].map { |l| l['id'] }
      expect(ids).to eq([recent_log.id])
    end

    it 'filters entries older than :until' do
      get :index, params: { until: 2.days.ago.iso8601 }

      ids = JSON.parse(response.body)['audit_logs'].map { |l| l['id'] }
      expect(ids).to eq([old_log.id])
    end

    it 'filters by actor' do
      get :index, params: { actor_id: recent_log.actor_id }

      ids = JSON.parse(response.body)['audit_logs'].map { |l| l['id'] }
      expect(ids).to eq([recent_log.id])
    end

    it 'filters by resource type and id together' do
      get :index, params: { resource_type: recent_log.resource_type, resource_id: recent_log.resource_id }

      ids = JSON.parse(response.body)['audit_logs'].map { |l| l['id'] }
      expect(ids).to eq([recent_log.id])
    end

    it 'rejects an unparseable :since value' do
      get :index, params: { since: 'yesterday-ish' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Invalid date format: yesterday-ish')
    end

    it 'rejects an out-of-range :until value' do
      get :index, params: { until: '2024-13-45T99:00:00Z' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Invalid date format: 2024-13-45T99:00:00Z')
    end
  end
end
