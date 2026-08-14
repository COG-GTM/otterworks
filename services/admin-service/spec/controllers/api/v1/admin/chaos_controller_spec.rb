require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  # The endpoint is unauthenticated only when the secret is unset; pin it so the
  # suite behaves the same inside the docker-compose container, which sets one.
  around { |example| with_env('CHAOS_SECRET' => nil) { example.run } }

  let(:redis) { instance_double(Redis) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
  end

  describe 'POST #trigger' do
    before { allow(redis).to receive(:setex) }

    it 'sets the chaos flag with a TTL and starts the traffic probe' do
      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:setex)
        .with('chaos:search-service:suggest_500', described_class::CHAOS_TTL_SECONDS, '1')
      expect(ChaosProbeService).to have_received(:start)
        .with(service: 'search-service', redis_key: 'chaos:search-service:suggest_500')
      expect(JSON.parse(response.body)).to eq(
        'status' => 'chaos_active',
        'key' => 'chaos:search-service:suggest_500',
        'expires_in' => described_class::CHAOS_TTL_SECONDS
      )
    end

    it 'rejects a scenario that does not belong to the service' do
      post :trigger, params: { service: 'search-service', scenario: 'slow_queries' }

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['error']).to eq('Invalid service/scenario combination')
      expect(body['valid']).to eq(described_class::VALID_SCENARIOS.stringify_keys)
      expect(redis).not_to have_received(:setex)
    end

    it 'rejects an unknown service' do
      post :trigger, params: { service: 'ghost-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(ChaosProbeService).not_to have_received(:start)
    end
  end

  describe 'DELETE #reset' do
    it 'clears the chaos keys and resolves incidents for chaos-managed services' do
      allow(redis).to receive(:keys).with('chaos:*').and_return(['chaos:search-service:suggest_500'])
      allow(redis).to receive(:del)
      incident = create(:incident, :investigating, affected_service: 'search-service')
      untouched = create(:incident, :investigating, affected_service: 'auth-service')

      delete :reset

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:del).with('chaos:search-service:suggest_500')
      expect(incident.reload.status).to eq('resolved')
      expect(untouched.reload.status).to eq('investigating')
      expect(JSON.parse(response.body)).to eq(
        'status' => 'reset',
        'cleared' => ['chaos:search-service:suggest_500'],
        'resolved_incidents' => [incident.id]
      )
    end

    it 'does not call del when there is nothing to clear' do
      allow(redis).to receive(:keys).and_return([])
      allow(redis).to receive(:del)

      delete :reset

      expect(redis).not_to have_received(:del)
      expect(JSON.parse(response.body)['cleared']).to eq([])
    end

    it 'skips incidents that cannot be resolved' do
      allow(redis).to receive(:keys).and_return([])
      allow(Rails.logger).to receive(:warn)
      incident = create(:incident, :investigating, affected_service: 'file-service')
      stub_const('Incident::VALID_TRANSITIONS', { 'investigating' => [] })

      delete :reset

      expect(JSON.parse(response.body)['resolved_incidents']).to eq([])
      expect(Rails.logger).to have_received(:warn).with(/skipping incident #{incident.id}/)
    end
  end

  describe 'chaos secret verification' do
    before do
      allow(redis).to receive(:keys).and_return([])
      allow(redis).to receive(:del)
    end

    it 'allows the request when no secret is configured' do
      with_env('CHAOS_SECRET' => nil) { delete :reset }

      expect(response).to have_http_status(:ok)
    end

    it 'allows the request when the secret is blank' do
      with_env('CHAOS_SECRET' => '') { delete :reset }

      expect(response).to have_http_status(:ok)
    end

    it 'accepts a matching X-Chaos-Secret header' do
      request.headers['X-Chaos-Secret'] = 'boom'

      with_env('CHAOS_SECRET' => 'boom') { delete :reset }

      expect(response).to have_http_status(:ok)
    end

    it 'rejects a missing or wrong header' do
      request.headers['X-Chaos-Secret'] = 'wrong'

      with_env('CHAOS_SECRET' => 'boom') { delete :reset }

      expect(response).to have_http_status(:unauthorized)
      expect(JSON.parse(response.body)['error']).to eq('Unauthorized')
    end
  end
end
