require 'rails_helper'

RSpec.describe Api::V1::Admin::HealthController do
  before { set_jwt_env(request) }

  describe 'GET #services' do
    it 'renders the aggregated health report' do
      report = {
        status: 'degraded',
        timestamp: Time.current.iso8601,
        services: [{ name: 'auth-service', status: 'healthy', latency_ms: 1.2, message: nil }],
        database: { status: 'healthy', latency_ms: 0.3 },
        redis: { status: 'unhealthy', message: 'refused' }
      }
      allow(HealthChecker).to receive(:check_all).and_return(report)

      get :services

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['status']).to eq('degraded')
      expect(body['services'].first).to include('name' => 'auth-service', 'status' => 'healthy')
      expect(body['redis']).to eq('status' => 'unhealthy', 'message' => 'refused')
    end
  end
end
