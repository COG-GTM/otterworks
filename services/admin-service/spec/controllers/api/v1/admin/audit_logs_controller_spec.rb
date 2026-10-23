require 'rails_helper'

RSpec.describe Api::V1::Admin::AuditLogsController do
  before { set_jwt_env(request) }

  describe 'GET #index' do
    let!(:logs) { create_list(:audit_log, 3) }

    it 'returns paginated audit logs' do
      get :index
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['audit_logs'].length).to eq(3)
    end

    it 'filters by action type' do
      create(:audit_log, action: 'feature_flag.created')
      get :index, params: { action_type: 'feature_flag.created' }
      body = JSON.parse(response.body)
      expect(body['audit_logs'].all? { |l| l['action'] == 'feature_flag.created' }).to be true
    end

    it 'filters by resource type' do
      get :index, params: { resource_type: 'AdminUser' }
      body = JSON.parse(response.body)
      expect(body['audit_logs'].all? { |l| l['resource_type'] == 'AdminUser' }).to be true
    end
  end

  describe 'GET #show' do
    let(:log) { create(:audit_log) }

    it 'returns the audit log entry' do
      get :show, params: { id: log.id }
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['id']).to eq(log.id)
    end
  end

  describe 'role enforcement' do
    let(:log) { create(:audit_log) }

    it 'forbids listing audit logs for non-admin roles' do
      set_jwt_env(request, role: 'user')
      get :index
      expect(response).to have_http_status(:forbidden)
      expect(response.parsed_body).not_to have_key('audit_logs')
    end

    it 'forbids reading an audit log entry for non-admin roles' do
      set_jwt_env(request, role: 'editor')
      get :show, params: { id: log.id }
      expect(response).to have_http_status(:forbidden)
    end
  end
end
