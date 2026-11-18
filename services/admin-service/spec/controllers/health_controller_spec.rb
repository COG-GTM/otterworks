require 'rails_helper'

RSpec.describe HealthController do
  describe 'GET /health' do
    it 'returns healthy status' do
      get :show
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['status']).to eq('healthy')
      expect(body['service']).to eq('admin-service')
    end
  end

  describe 'GET /metrics' do
    it 'returns prometheus metrics' do
      get :metrics
      expect(response).to have_http_status(:ok)
      expect(response.content_type).to include('text/plain')
      expect(response.body).to include('admin_service_up 1')
    end
  end
end

RSpec.describe HealthController, 'degraded dependencies' do
  it 'returns 503 when the database is unreachable' do
    allow(ActiveRecord::Base.connection).to receive(:execute).and_raise(ActiveRecord::ConnectionNotEstablished)
    get :show
    expect(response).to have_http_status(:service_unavailable)
    expect(JSON.parse(response.body)).to include('status' => 'degraded', 'database' => 'disconnected')
  end

  it 'reports zero counts when metric queries fail' do
    allow(AdminUser).to receive(:count).and_raise(ActiveRecord::StatementInvalid)
    allow(AdminUser).to receive(:active).and_raise(ActiveRecord::StatementInvalid)
    allow(FeatureFlag).to receive(:count).and_raise(ActiveRecord::StatementInvalid)
    allow(FeatureFlag).to receive(:enabled).and_raise(ActiveRecord::StatementInvalid)

    get :metrics

    %w[admin_users_total admin_users_active admin_feature_flags_total admin_feature_flags_enabled].each do |m|
      expect(response.body).to include("#{m} 0")
    end
  end
end
