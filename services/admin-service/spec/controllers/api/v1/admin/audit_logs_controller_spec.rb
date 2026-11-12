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

  describe 'authorization' do
    let!(:log) { create(:audit_log) }

    %w[user editor viewer].each do |role|
      context "with a #{role} role" do
        before { set_jwt_env(request, role: role) }

        it 'forbids listing audit logs' do
          get :index
          expect(response).to have_http_status(:forbidden)
          expect(response.body).not_to include(log.actor_email.to_s)
        end

        it 'forbids reading an audit log entry' do
          get :show, params: { id: log.id }
          expect(response).to have_http_status(:forbidden)
          expect(response.body).not_to include(log.actor_email.to_s)
        end
      end
    end

    context 'without a role claim' do
      before { set_jwt_env(request, role: nil) }

      it 'forbids listing audit logs' do
        get :index
        expect(response).to have_http_status(:forbidden)
      end
    end

    %w[admin super_admin owner].each do |role|
      context "with an #{role} role" do
        before { set_jwt_env(request, role: role) }

        it 'allows listing audit logs' do
          get :index
          expect(response).to have_http_status(:ok)
        end

        it 'allows reading an audit log entry' do
          get :show, params: { id: log.id }
          expect(response).to have_http_status(:ok)
        end
      end
    end
  end
end
