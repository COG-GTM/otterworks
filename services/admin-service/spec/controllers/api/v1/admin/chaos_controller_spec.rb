require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return(nil)
  end

  def json
    JSON.parse(response.body)
  end

  describe 'POST #trigger' do
    it 'sets the chaos flag with a TTL and starts the probe' do
      allow(redis).to receive(:setex)

      post :trigger, params: { service: 'search-service', scenario: 'suggest_500' }

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:setex).with('chaos:search-service:suggest_500', 600, '1')
      expect(ChaosProbeService).to have_received(:start)
        .with(service: 'search-service', redis_key: 'chaos:search-service:suggest_500')
      expect(json).to eq('status' => 'chaos_active', 'key' => 'chaos:search-service:suggest_500', 'expires_in' => 600)
    end

    it 'rejects a mismatched service/scenario' do
      post :trigger, params: { service: 'search-service', scenario: 'upload_s3_error' }
      expect(response).to have_http_status(:unprocessable_entity)
      expect(json['valid']).to eq(described_class::VALID_SCENARIOS)
      expect(ChaosProbeService).not_to have_received(:start)
    end

    it 'rejects an unknown service' do
      post :trigger, params: { service: 'nope', scenario: 'x' }
      expect(response).to have_http_status(:unprocessable_entity)
    end
  end

  describe 'DELETE #reset' do
    it 'clears flags and resolves active incidents for chaos-managed services only' do
      allow(redis).to receive(:keys).with('chaos:*').and_return(%w[chaos:file-service:upload_s3_error])
      allow(redis).to receive(:del)
      open_file = create(:incident, affected_service: 'file-service')
      investigating_search = create(:incident, :investigating, affected_service: 'search-service')
      unrelated = create(:incident, affected_service: 'auth-service')
      already_resolved = create(:incident, :resolved, affected_service: 'document-service')

      delete :reset

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:del).with('chaos:file-service:upload_s3_error')
      expect(json['cleared']).to eq(%w[chaos:file-service:upload_s3_error])
      expect(json['resolved_incidents']).to contain_exactly(open_file.id, investigating_search.id)
      expect(unrelated.reload.status).to eq('open')
      expect(already_resolved.reload.status).to eq('resolved')
    end

    it 'skips DEL when no flags are set' do
      allow(redis).to receive(:keys).and_return([])
      allow(redis).to receive(:del)

      delete :reset

      expect(redis).not_to have_received(:del)
      expect(json).to eq('status' => 'reset', 'cleared' => [], 'resolved_incidents' => [])
    end

    it 'skips incidents that cannot transition' do
      allow(redis).to receive(:keys).and_return([])
      create(:incident, affected_service: 'file-service')
      allow_any_instance_of(Incident).to receive(:resolve!).and_raise(Incident::InvalidTransitionError, 'raced')

      delete :reset

      expect(response).to have_http_status(:ok)
      expect(json['resolved_incidents']).to eq([])
    end
  end

  describe 'X-Chaos-Secret' do
    before do
      allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return('s3cret')
      allow(redis).to receive(:keys).and_return([])
    end

    it 'rejects a missing secret' do
      delete :reset
      expect(response).to have_http_status(:unauthorized)
    end

    it 'rejects a wrong secret' do
      request.headers['X-Chaos-Secret'] = 'wrong'
      delete :reset
      expect(response).to have_http_status(:unauthorized)
    end

    it 'accepts the configured secret' do
      request.headers['X-Chaos-Secret'] = 's3cret'
      delete :reset
      expect(response).to have_http_status(:ok)
    end

    it 'allows requests when the secret is configured as empty' do
      allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return('')
      delete :reset
      expect(response).to have_http_status(:ok)
    end
  end
end
