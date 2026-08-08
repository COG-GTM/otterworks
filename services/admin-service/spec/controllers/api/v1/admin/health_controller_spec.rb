require 'rails_helper'

RSpec.describe Api::V1::Admin::HealthController do
  before { set_jwt_env(request) }

  describe 'GET #services' do
    it 'renders the aggregated HealthChecker report' do
      report = { status: 'degraded', services: [{ name: 'auth-service', status: 'unhealthy' }] }
      allow(HealthChecker).to receive(:check_all).and_return(report)

      get :services

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['status']).to eq('degraded')
      expect(body['services'].first['name']).to eq('auth-service')
    end
  end
end
