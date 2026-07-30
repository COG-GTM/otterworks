require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis) }

  before do
    set_jwt_env(request)
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
    allow(Rails.logger).to receive(:warn)
  end

  describe 'POST #trigger' do
    it 'sets the chaos flag and starts the probe' do
      allow(redis).to receive(:setex)

      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body).to include('status' => 'chaos_active', 'key' => 'chaos:search-service:suggest_500',
                              'expires_in' => described_class::CHAOS_TTL_SECONDS)
      expect(redis).to have_received(:setex)
        .with('chaos:search-service:suggest_500', described_class::CHAOS_TTL_SECONDS, '1')
      expect(ChaosProbeService).to have_received(:start)
        .with(service: 'search-service', redis_key: 'chaos:search-service:suggest_500')
    end

    it 'rejects a service/scenario mismatch' do
      post :trigger, params: { service: 'search-service', scenario: 'slow_queries' }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['valid']).to eq(described_class::VALID_SCENARIOS.stringify_keys)
      expect(ChaosProbeService).not_to have_received(:start)
    end
  end

  describe 'DELETE #reset' do
    before { allow(redis).to receive(:keys).with('chaos:*').and_return(['chaos:search-service:suggest_500']) }

    it 'clears the flags and resolves open chaos incidents' do
      allow(redis).to receive(:del)
      incident = create(:incident, :investigating, affected_service: 'search-service')

      delete :reset

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['cleared']).to eq(['chaos:search-service:suggest_500'])
      expect(body['resolved_incidents']).to eq([incident.id])
      expect(incident.reload.status).to eq('resolved')
      expect(redis).to have_received(:del).with('chaos:search-service:suggest_500')
    end

    it 'skips incidents that cannot be resolved' do
      allow(redis).to receive(:del)
      incident = create(:incident, affected_service: 'file-service')
      stub_const('Incident::VALID_TRANSITIONS', { 'open' => [] })

      delete :reset

      expect(JSON.parse(response.body)['resolved_incidents']).to be_empty
      expect(incident.reload.status).to eq('open')
      expect(Rails.logger).to have_received(:warn).with(/skipping incident/)
    end

    it 'does not call del when no flags are set' do
      allow(redis).to receive(:keys).with('chaos:*').and_return([])
      allow(redis).to receive(:del)

      delete :reset

      expect(redis).not_to have_received(:del)
      expect(JSON.parse(response.body)['cleared']).to eq([])
    end
  end

  describe 'secret verification' do
    it 'rejects a wrong secret when CHAOS_SECRET is configured' do
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return('s3cret')
      request.headers['X-Chaos-Secret'] = 'wrong'

      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:unauthorized)
    end

    it 'accepts the matching secret' do
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return('s3cret')
      allow(redis).to receive(:setex)
      request.headers['X-Chaos-Secret'] = 's3cret'

      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:ok)
    end
  end
end
