require 'rails_helper'

RSpec.describe Api::V1::Admin::AuditLogsController do
  before { set_jwt_env(request) }

  describe 'GET #index time filters' do
    let!(:old_log) { create(:audit_log, created_at: 10.days.ago) }
    let!(:recent_log) { create(:audit_log, created_at: 1.hour.ago) }

    it 'filters with since' do
      get :index, params: { since: 2.days.ago.iso8601 }

      expect(JSON.parse(response.body)['audit_logs'].map { |l| l['id'] }).to eq([recent_log.id])
    end

    it 'filters with until' do
      get :index, params: { until: 2.days.ago.iso8601 }

      expect(JSON.parse(response.body)['audit_logs'].map { |l| l['id'] }).to eq([old_log.id])
    end

    it 'returns 400 for an unparseable since value' do
      get :index, params: { since: 'yesterday-ish' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Invalid date format: yesterday-ish')
    end

    it 'returns 400 for a malformed date that raises while parsing' do
      get :index, params: { until: '2026-13-45T99:99:99Z' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to match(/Invalid date format/)
    end
  end
end
