require 'rails_helper'

RSpec.describe Api::V1::Admin::HealthController do
  before { set_jwt_env(request) }

  describe 'GET #services' do
    it 'renders the aggregated report from HealthChecker' do
      report = {
        status: 'degraded',
        timestamp: Time.current.iso8601,
        services: [{ name: 'auth-service', status: 'unhealthy', latency_ms: 12.3, message: 'boom' }],
        database: { status: 'healthy', latency_ms: 0.4 },
        redis: { status: 'healthy', latency_ms: 0.2 }
      }
      allow(HealthChecker).to receive(:check_all).and_return(report)

      get :services

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['status']).to eq('degraded')
      expect(body['services'].first).to include('name' => 'auth-service', 'status' => 'unhealthy')
      expect(body['database']).to include('status' => 'healthy')
    end
  end
end
