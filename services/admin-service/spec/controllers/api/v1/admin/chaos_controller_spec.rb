require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis, setex: 'OK', keys: [], del: 0, smembers: []) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
  end

  around do |example|
    original = ENV.fetch('CHAOS_SECRET', nil)
    ENV.delete('CHAOS_SECRET')
    example.run
  ensure
    if original.nil?
      ENV.delete('CHAOS_SECRET')
    else
      ENV['CHAOS_SECRET'] = original
    end
  end

  def open_incident(service)
    Incident.create!(title: "#{service} down", description: 'p95 latency high', severity: 'critical',
                     status: 'open', affected_service: service)
  end

  let(:valid_params) { { service: 'search-service', scenario: 'suggest_500' } }

  describe 'POST #trigger' do
    it 'rejects a request with no authenticated user even when CHAOS_SECRET is unset' do
      post :trigger, params: valid_params

      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
      expect(ChaosProbeService).not_to have_received(:start)
    end

    it 'rejects a non-admin user' do
      set_jwt_env(request, role: 'user')
      post :trigger, params: valid_params

      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
      expect(ChaosProbeService).not_to have_received(:start)
    end

    it 'sets the chaos flag and starts the probe for an admin' do
      set_jwt_env(request, role: 'admin')
      post :trigger, params: valid_params

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:setex).with('chaos:search-service:suggest_500', 600, '1')
      expect(ChaosProbeService).to have_received(:start)
        .with(service: 'search-service', redis_key: 'chaos:search-service:suggest_500')
    end

    context 'when CHAOS_SECRET is set' do
      before { ENV['CHAOS_SECRET'] = 's3cret' }

      it 'rejects an admin without the matching X-Chaos-Secret header' do
        set_jwt_env(request, role: 'admin')
        request.headers['X-Chaos-Secret'] = 'wrong'
        post :trigger, params: valid_params

        expect(response).to have_http_status(:unauthorized)
        expect(redis).not_to have_received(:setex)
      end

      it 'rejects a non-admin even with the matching secret' do
        set_jwt_env(request, role: 'user')
        request.headers['X-Chaos-Secret'] = 's3cret'
        post :trigger, params: valid_params

        expect(response).to have_http_status(:forbidden)
        expect(redis).not_to have_received(:setex)
      end

      it 'accepts an admin with the matching secret' do
        set_jwt_env(request, role: 'admin')
        request.headers['X-Chaos-Secret'] = 's3cret'
        post :trigger, params: valid_params

        expect(response).to have_http_status(:ok)
      end
    end
  end

  describe 'DELETE #reset' do
    it 'does not resolve incidents or clear flags for an unauthenticated caller' do
      incident = open_incident('file-service')
      allow(redis).to receive(:smembers).with('chaos_incidents:file-service').and_return([incident.id])
      delete :reset

      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:keys)
      expect(redis).not_to have_received(:del)
      expect(incident.reload.status).to eq('open')
    end

    it 'does not resolve incidents or clear flags for a non-admin user' do
      incident = open_incident('file-service')
      allow(redis).to receive(:smembers).with('chaos_incidents:file-service').and_return([incident.id])
      set_jwt_env(request, role: 'user')
      delete :reset

      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:keys)
      expect(redis).not_to have_received(:del)
      expect(incident.reload.status).to eq('open')
    end

    it 'clears flags and resolves only incidents attributed to a chaos run' do
      allow(redis).to receive(:keys).with('chaos:*').and_return(['chaos:file-service:upload_s3_error'])
      chaos = open_incident('file-service')
      unattributed = open_incident('file-service')
      other_service = open_incident('search-service')
      allow(redis).to receive(:smembers).with('chaos_incidents:file-service').and_return([chaos.id])

      set_jwt_env(request, role: 'admin')
      delete :reset

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:del).with('chaos:file-service:upload_s3_error')
      expect(redis).to have_received(:del).with('chaos_incidents:file-service')
      expect(response.parsed_body['resolved_incidents']).to eq([chaos.id])
      expect(chaos.reload.status).to eq('resolved')
      expect(unattributed.reload.status).to eq('open')
      expect(other_service.reload.status).to eq('open')
    end

    it 'ignores registered ids that belong to another service' do
      foreign = open_incident('search-service')
      allow(redis).to receive(:smembers).with('chaos_incidents:file-service').and_return([foreign.id])

      set_jwt_env(request, role: 'admin')
      delete :reset

      expect(response).to have_http_status(:ok)
      expect(foreign.reload.status).to eq('open')
    end
  end
end
