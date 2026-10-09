require 'rails_helper'

RSpec.describe Api::V1::Admin::HealthController do
  let(:report) { { status: 'healthy', services: [], database: { status: 'healthy' }, redis: { status: 'healthy' } } }

  before do
    set_jwt_env(request)
    allow(HealthChecker).to receive(:check_all).and_return(report)
  end

  describe 'GET #services' do
    it 'returns the health report to admins' do
      get :services
      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['status']).to eq('healthy')
    end

    %w[USER user viewer editor].each do |role|
      it "forbids the health report for the #{role} role" do
        set_jwt_env(request, role: role)
        get :services
        expect(response).to have_http_status(:forbidden)
        expect(HealthChecker).not_to have_received(:check_all)
      end
    end

    it 'forbids the health report when no role is present' do
      request.env.delete('jwt.user_role')
      get :services
      expect(response).to have_http_status(:forbidden)
    end
  end
end
