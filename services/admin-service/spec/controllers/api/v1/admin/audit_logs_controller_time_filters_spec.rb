require 'rails_helper'

# Complements spec/controllers/api/v1/admin/audit_logs_controller_spec.rb by
# covering the time-window filters and their error handling.
RSpec.describe Api::V1::Admin::AuditLogsController do
  before { set_jwt_env(request) }

  let!(:old_log) { create(:audit_log, created_at: 10.days.ago) }
  let!(:recent_log) { create(:audit_log, created_at: 1.hour.ago) }

  def ids
    JSON.parse(response.body)['audit_logs'].map { |l| l['id'] }
  end

  it 'filters with since' do
    get :index, params: { since: 2.days.ago.iso8601 }

    expect(ids).to eq([recent_log.id])
  end

  it 'filters with until' do
    get :index, params: { until: 2.days.ago.iso8601 }

    expect(ids).to eq([old_log.id])
  end

  it 'filters by actor' do
    get :index, params: { actor_id: recent_log.actor_id }

    expect(ids).to eq([recent_log.id])
  end

  it 'filters by resource id' do
    get :index, params: { resource_type: 'AdminUser', resource_id: old_log.resource_id }

    expect(ids).to eq([old_log.id])
  end

  it 'returns 400 for an unparseable since value' do
    get :index, params: { since: 'yesterday-ish' }

    expect(response).to have_http_status(:bad_request)
    expect(JSON.parse(response.body)['error']).to eq('Invalid date format: yesterday-ish')
  end

  it 'returns 400 for an out-of-range date' do
    get :index, params: { until: '2024-13-45' }

    expect(response).to have_http_status(:bad_request)
    expect(JSON.parse(response.body)['error']).to match(/Invalid date format/)
  end
end
