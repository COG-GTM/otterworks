require 'rails_helper'

# Complements spec/controllers/health_controller_spec.rb by exercising the
# degraded paths, where the database or the metric queries are unavailable.
RSpec.describe HealthController do
  describe 'GET /health when the database is unreachable' do
    it 'reports degraded with a 503' do
      allow(ActiveRecord::Base).to receive(:connection).and_raise(ActiveRecord::ConnectionNotEstablished)

      get :show

      expect(response).to have_http_status(:service_unavailable)
      body = JSON.parse(response.body)
      expect(body).to include('status' => 'degraded', 'database' => 'disconnected')
    end
  end

  describe 'GET /health' do
    it 'reports the configured application version' do
      with_env('APP_VERSION' => '9.9.9') { get :show }

      expect(JSON.parse(response.body)['version']).to eq('9.9.9')
    end
  end

  describe 'GET /metrics' do
    it 'counts the persisted admin users and feature flags' do
      create_list(:admin_user, 2)
      create(:admin_user, :suspended)
      create(:feature_flag, :enabled)
      create(:feature_flag)

      get :metrics

      expect(response.body).to include('admin_users_total 3', 'admin_users_active 2',
                                       'admin_feature_flags_total 2', 'admin_feature_flags_enabled 1')
    end

    it 'falls back to zeroes when the metric queries fail' do
      allow(AdminUser).to receive(:count).and_raise(ActiveRecord::StatementInvalid, 'gone')
      allow(AdminUser).to receive(:active).and_raise(ActiveRecord::StatementInvalid, 'gone')
      allow(FeatureFlag).to receive(:count).and_raise(ActiveRecord::StatementInvalid, 'gone')
      allow(FeatureFlag).to receive(:enabled).and_raise(ActiveRecord::StatementInvalid, 'gone')

      get :metrics

      expect(response).to have_http_status(:ok)
      expect(response.body).to include('admin_users_total 0', 'admin_users_active 0',
                                       'admin_feature_flags_total 0', 'admin_feature_flags_enabled 0')
    end
  end
end
