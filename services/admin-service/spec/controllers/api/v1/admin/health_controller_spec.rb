require 'rails_helper'

RSpec.describe Api::V1::Admin::HealthController do
  before { set_jwt_env(request) }

  it 'returns the aggregated health report' do
    report = { status: 'degraded', services: [{ name: 'auth-service', status: 'unhealthy' }] }
    allow(HealthChecker).to receive(:check_all).and_return(report)

    get :services

    expect(response).to have_http_status(:ok)
    expect(JSON.parse(response.body)).to eq(report.deep_stringify_keys)
  end
end

RSpec.describe Api::V1::Admin::HealthController, 'unexpected errors' do
  before { set_jwt_env(request) }

  it 'renders a generic 500 via ApplicationController' do
    allow(HealthChecker).to receive(:check_all).and_raise(RuntimeError, 'kaboom')
    allow(Rails.logger).to receive(:error)

    get :services

    expect(response).to have_http_status(:internal_server_error)
    expect(JSON.parse(response.body)).to eq('error' => 'Internal server error')
    expect(Rails.logger).to have_received(:error).with('Unhandled error: kaboom')
  end
end
