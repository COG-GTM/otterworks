require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis) }

  before do
    set_jwt_env(request)
    allow(Redis).to receive(:new).and_return(redis)
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return(nil)
    allow(ChaosProbeService).to receive(:start)
  end

  describe 'POST #trigger' do
    it 'sets the chaos flag with a TTL and starts the probe' do
      allow(redis).to receive(:setex)

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
      expect(JSON.parse(response.body)['valid']).to eq(described_class::VALID_SCENARIOS.stringify_keys)
      expect(ChaosProbeService).not_to have_received(:start)
    end

    it 'rejects an unknown service' do
      post :trigger, params: { service: 'ghost-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:unprocessable_entity)
    end
  end

  describe 'DELETE #reset' do
    it 'clears the chaos keys and resolves chaos-managed incidents' do
      open_incident = create(:incident, status: 'open', affected_service: 'search-service')
      investigating = create(:incident, :investigating, affected_service: 'document-service')
      untouched = create(:incident, status: 'open', affected_service: 'auth-service')
      allow(redis).to receive_messages(keys: ['chaos:search-service:suggest_500'], del: 1)

      delete :reset

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:del).with('chaos:search-service:suggest_500')
      body = JSON.parse(response.body)
      expect(body['status']).to eq('reset')
      expect(body['cleared']).to eq(['chaos:search-service:suggest_500'])
      expect(body['resolved_incidents']).to contain_exactly(open_incident.id, investigating.id)
      expect(untouched.reload.status).to eq('open')
    end

    it 'skips the delete when no chaos keys exist' do
      allow(redis).to receive_messages(keys: [], del: 0)

      delete :reset

      expect(redis).not_to have_received(:del)
      expect(JSON.parse(response.body)['cleared']).to eq([])
    end

    it 'skips incidents that cannot be resolved' do
      incident = create(:incident, status: 'open', affected_service: 'search-service')
      relation = instance_double(ActiveRecord::Relation)
      allow(redis).to receive_messages(keys: [], del: 0)
      allow(Incident).to receive(:where).and_call_original
      allow(Incident).to receive(:where).with(affected_service: 'search-service').and_return(relation)
      allow(relation).to receive(:where).with(status: %w[open investigating]).and_return(relation)
      allow(relation).to receive(:each).and_yield(incident)
      allow(incident).to receive(:resolve!).and_raise(Incident::InvalidTransitionError, 'bad state')
      allow(Rails.logger).to receive(:warn)

      delete :reset

      expect(JSON.parse(response.body)['resolved_incidents']).to eq([])
      expect(Rails.logger).to have_received(:warn).with(/CHAOS RESET: skipping incident #{incident.id}/)
    end
  end

  describe 'chaos secret verification' do
    before { allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return('open-sesame') }

    it 'rejects a request without the header' do
      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:unauthorized)
      expect(ChaosProbeService).not_to have_received(:start)
    end

    it 'accepts the matching secret' do
      allow(redis).to receive(:setex)
      request.headers['X-Chaos-Secret'] = 'open-sesame'

      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:ok)
    end

    it 'rejects a mismatched secret' do
      request.headers['X-Chaos-Secret'] = 'wrong'

      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:unauthorized)
    end

    it 'allows any request when the secret is configured empty' do
      allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return('')
      allow(redis).to receive(:setex)

      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:ok)
    end
  end

  describe 'redis client construction' do
    it 'builds the client from REDIS_HOST and REDIS_PORT' do
      allow(ENV).to receive(:fetch).with('REDIS_HOST', 'localhost').and_return('redis.internal')
      allow(ENV).to receive(:fetch).with('REDIS_PORT', '6379').and_return('6380')
      allow(ENV).to receive(:fetch).with('REDIS_URL', 'redis://redis.internal:6380/0')
                                   .and_return('redis://redis.internal:6380/0')
      allow(redis).to receive(:setex)

      post :trigger, params: { service: 'file-service', scenario: 'upload_s3_error' }

      expect(Redis).to have_received(:new).with(url: 'redis://redis.internal:6380/0', timeout: 2)
    end
  end
end
