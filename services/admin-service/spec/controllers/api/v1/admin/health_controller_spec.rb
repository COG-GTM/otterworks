require 'rails_helper'

RSpec.describe Api::V1::Admin::HealthController do
  before { set_jwt_env(request) }

  describe 'GET #services' do
    it 'returns service health for admins' do
      allow(HealthChecker).to receive(:check_all).and_return({ status: 'healthy', services: [] })
      get :services
      expect(response).to have_http_status(:ok)
      expect(response.parsed_body['status']).to eq('healthy')
    end

    it 'forbids service health for non-admin roles' do
      allow(HealthChecker).to receive(:check_all)
      set_jwt_env(request, role: 'user')
      get :services
      expect(response).to have_http_status(:forbidden)
      expect(HealthChecker).not_to have_received(:check_all)
    end
  end
end
