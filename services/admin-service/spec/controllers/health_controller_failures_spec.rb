require 'rails_helper'

RSpec.describe HealthController do
  describe 'GET #show' do
    it 'reports degraded and 503 when the database is unreachable' do
      allow(ActiveRecord::Base).to receive(:connection).and_raise(ActiveRecord::ConnectionNotEstablished)

      get :show

      expect(response).to have_http_status(:service_unavailable)
      expect(JSON.parse(response.body)).to include('status' => 'degraded', 'database' => 'disconnected')
    end
  end

  describe 'GET #metrics' do
    it 'falls back to zero for every gauge whose query fails' do
      allow(AdminUser).to receive(:count).and_raise(ActiveRecord::StatementInvalid)
      allow(AdminUser).to receive(:active).and_raise(ActiveRecord::StatementInvalid)
      allow(FeatureFlag).to receive(:count).and_raise(ActiveRecord::StatementInvalid)
      allow(FeatureFlag).to receive(:enabled).and_raise(ActiveRecord::StatementInvalid)

      get :metrics

      expect(response).to have_http_status(:ok)
      expect(response.body).to include(
        'admin_users_total 0',
        'admin_users_active 0',
        'admin_feature_flags_total 0',
        'admin_feature_flags_enabled 0'
      )
    end
  end
end
