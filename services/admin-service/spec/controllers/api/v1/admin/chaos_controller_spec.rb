require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis) }
  let(:key) { 'chaos:search-service:suggest_500' }
  let(:ttl) { described_class::CHAOS_TTL_SECONDS }

  before do
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return(nil)
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start).and_return(:started)
  end

  describe 'POST #trigger' do
    it 'sets the chaos key only if absent and starts the probe' do
      allow(redis).to receive(:set).with(key, '1', nx: true, ex: ttl).and_return(true)

      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['status']).to eq('chaos_active')
      expect(body['expires_in']).to eq(ttl)
      expect(ChaosProbeService).to have_received(:start).with(service: 'search-service', redis_key: key)
    end

    it 'does not extend an active chaos window on repeat triggers' do
      allow(redis).to receive(:set).with(key, '1', nx: true, ex: ttl).and_return(false)
      allow(redis).to receive(:ttl).with(key).and_return(420)
      allow(redis).to receive(:setex)
      allow(redis).to receive(:expire)

      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:ok)
      expect(response.parsed_body['expires_in']).to eq(420)
      expect(redis).not_to have_received(:setex)
      expect(redis).not_to have_received(:expire)
    end

    it 'rejects unknown service/scenario combinations without touching redis or probes' do
      allow(redis).to receive(:set)

      post :trigger, params: { service: 'search-service', scenario: 'upload_s3_error' }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(redis).not_to have_received(:set)
      expect(ChaosProbeService).not_to have_received(:start)
    end
  end
end
