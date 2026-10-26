require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis, setex: 'OK', keys: [], del: 0) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
  end

  it 'refuses to set a chaos flag for a regular user' do
    set_jwt_env(request, role: 'user')
    post :trigger, params: { service: 'file-service', scenario: 'upload_s3_error' }
    expect(response).to have_http_status(:forbidden)
    expect(redis).not_to have_received(:setex)
  end

  it 'refuses to clear chaos flags for a regular user' do
    set_jwt_env(request, role: 'user')
    delete :reset
    expect(response).to have_http_status(:forbidden)
    expect(redis).not_to have_received(:keys)
  end

  it 'lets an admin set a chaos flag' do
    set_jwt_env(request, role: 'admin')
    post :trigger, params: { service: 'file-service', scenario: 'upload_s3_error' }
    expect(response).to have_http_status(:ok)
    expect(redis).to have_received(:setex).with('chaos:file-service:upload_s3_error', 600, '1')
  end
end
