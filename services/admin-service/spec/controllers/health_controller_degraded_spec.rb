require 'rails_helper'

# Complements spec/controllers/health_controller_spec.rb by exercising the
# failure branches of the health payload and the Prometheus metrics.
RSpec.describe HealthController do
  describe 'GET /health when the database is unreachable' do
    it 'reports degraded with a 503' do
      allow(ActiveRecord::Base.connection).to receive(:execute).with('SELECT 1')
                                                               .and_raise(ActiveRecord::StatementInvalid, 'down')

      get :show

      expect(response).to have_http_status(:service_unavailable)
      body = JSON.parse(response.body)
      expect(body['status']).to eq('degraded')
      expect(body['database']).to eq('disconnected')
    end
  end

  describe 'GET /metrics' do
    it 'reports the real counts' do
      create_list(:admin_user, 2)
      create(:admin_user, :suspended)
      create(:feature_flag, enabled: true)

      get :metrics

      expect(response.body).to include('admin_users_total 3')
      expect(response.body).to include('admin_users_active 2')
      expect(response.body).to include('admin_feature_flags_total 1')
      expect(response.body).to include('admin_feature_flags_enabled 1')
    end

    it 'falls back to zero when the counts raise' do
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
