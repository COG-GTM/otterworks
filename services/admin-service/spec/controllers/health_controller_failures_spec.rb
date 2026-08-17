require 'rails_helper'

RSpec.describe HealthController do
  describe 'GET /health when the database is unreachable' do
    it 'reports degraded with a 503' do
      allow(ActiveRecord::Base.connection).to receive(:execute).and_raise(ActiveRecord::ConnectionNotEstablished)

      get :show

      expect(response).to have_http_status(:service_unavailable)
      body = JSON.parse(response.body)
      expect(body['status']).to eq('degraded')
      expect(body['database']).to eq('disconnected')
    end
  end

  describe 'GET /metrics' do
    it 'reports the current counts' do
      create(:admin_user, status: 'active')
      create(:admin_user, :suspended)
      create(:feature_flag, :enabled)

      get :metrics

      expect(response.body).to include('admin_users_total 2', 'admin_users_active 1',
                                       'admin_feature_flags_total 1', 'admin_feature_flags_enabled 1')
    end

    it 'falls back to zero for every gauge whose query fails' do
      allow(AdminUser).to receive(:count).and_raise(ActiveRecord::StatementInvalid)
      allow(AdminUser).to receive(:active).and_raise(ActiveRecord::StatementInvalid)
      allow(FeatureFlag).to receive(:count).and_raise(ActiveRecord::StatementInvalid)
      allow(FeatureFlag).to receive(:enabled).and_raise(ActiveRecord::StatementInvalid)

      get :metrics

      expect(response).to have_http_status(:ok)
      expect(response.body).to include('admin_users_total 0', 'admin_users_active 0',
                                       'admin_feature_flags_total 0', 'admin_feature_flags_enabled 0')
    end
  end
end
