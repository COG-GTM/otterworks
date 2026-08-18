require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis) }

  before do
    stub_const('ENV', ENV.to_hash.except('CHAOS_SECRET'))
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
  end

  describe 'POST #trigger' do
    it 'sets the chaos flag with a TTL and starts the probe' do
      allow(redis).to receive(:setex)

      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)).to eq(
        'status' => 'chaos_active',
        'key' => 'chaos:search-service:suggest_500',
        'expires_in' => described_class::CHAOS_TTL_SECONDS
      )
      expect(redis).to have_received(:setex)
        .with('chaos:search-service:suggest_500', described_class::CHAOS_TTL_SECONDS, '1')
      expect(ChaosProbeService).to have_received(:start)
        .with(service: 'search-service', redis_key: 'chaos:search-service:suggest_500')
    end

    it 'rejects a service/scenario mismatch' do
      post :trigger, params: { service: 'search-service', scenario: 'slow_queries' }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['valid']).to eq(described_class::VALID_SCENARIOS)
      expect(ChaosProbeService).not_to have_received(:start)
    end

    it 'rejects an unknown service' do
      post :trigger, params: { service: 'nope-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:unprocessable_entity)
    end
  end

  describe 'DELETE #reset' do
    it 'clears the chaos flags and resolves chaos-service incidents' do
      resolvable = create(:incident, :investigating, affected_service: 'file-service')
      untouched = create(:incident, status: 'open', affected_service: 'auth-service')
      allow(redis).to receive(:keys).with('chaos:*').and_return(['chaos:file-service:upload_s3_error'])
      allow(redis).to receive(:del)

      delete :reset

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['status']).to eq('reset')
      expect(body['cleared']).to eq(['chaos:file-service:upload_s3_error'])
      expect(body['resolved_incidents']).to eq([resolvable.id])
      expect(redis).to have_received(:del).with('chaos:file-service:upload_s3_error')
      expect(resolvable.reload.status).to eq('resolved')
      expect(untouched.reload.status).to eq('open')
    end

    it 'does not call del when no flags are set' do
      allow(redis).to receive(:keys).and_return([])
      allow(redis).to receive(:del)

      delete :reset

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['cleared']).to eq([])
      expect(redis).not_to have_received(:del)
    end

    it 'skips incidents that refuse to resolve' do
      create(:incident, :investigating, affected_service: 'document-service')
      allow(redis).to receive(:keys).and_return([])
      allow_any_instance_of(Incident).to receive(:resolve!).and_raise(Incident::InvalidTransitionError, 'stuck')
      allow(Rails.logger).to receive(:warn)

      delete :reset

      expect(JSON.parse(response.body)['resolved_incidents']).to eq([])
      expect(Rails.logger).to have_received(:warn).with(/CHAOS RESET: skipping incident/)
    end
  end

  describe 'chaos secret verification' do
    before do
      stub_const('ENV', ENV.to_hash.merge('CHAOS_SECRET' => 'shhh'))
      allow(redis).to receive(:setex)
    end

    it 'allows a request carrying the right secret' do
      request.headers['X-Chaos-Secret'] = 'shhh'

      post :trigger, params: { service: 'file-service', scenario: 'upload_s3_error' }

      expect(response).to have_http_status(:ok)
    end

    it 'rejects a request with the wrong secret' do
      request.headers['X-Chaos-Secret'] = 'wrong'

      post :trigger, params: { service: 'file-service', scenario: 'upload_s3_error' }

      expect(response).to have_http_status(:unauthorized)
      expect(redis).not_to have_received(:setex)
    end

    it 'rejects a request with no secret at all' do
      post :trigger, params: { service: 'file-service', scenario: 'upload_s3_error' }

      expect(response).to have_http_status(:unauthorized)
    end

    # Demo-mode behaviour: an unconfigured CHAOS_SECRET deliberately fails open.
    it 'fails open for an unauthenticated request when the secret is unconfigured' do
      stub_const('ENV', ENV.to_hash.merge('CHAOS_SECRET' => ''))

      post :trigger, params: { service: 'file-service', scenario: 'upload_s3_error' }

      expect(response).to have_http_status(:ok)
    end
  end
end
