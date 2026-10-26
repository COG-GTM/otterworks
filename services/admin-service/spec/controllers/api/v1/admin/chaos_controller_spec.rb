require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis, setex: 'OK', keys: [], del: 0, get: nil, set: true, expire: true) }

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

  def open_incident(service, description: 'real outage', reporter_id: nil, created_at: Time.current)
    Incident.create!(title: "#{service} down", description: description, severity: 'critical',
                     status: 'open', affected_service: service, reporter_id: reporter_id,
                     created_at: created_at)
  end

  def alert_incident(service, **opts)
    open_incident(service, description: "p95 high\n\n#{Api::V1::Admin::AlertsController::AUTO_INCIDENT_SOURCE}", **opts)
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
      expect(redis).to have_received(:set)
        .with('chaos_window:search-service', kind_of(String), nx: true, ex: 3600)
    end

    it 'keeps the original chaos window start when the flag is renewed' do
      allow(redis).to receive(:set).and_return(false)
      set_jwt_env(request, role: 'admin')
      post :trigger, params: valid_params

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:expire).with('chaos_window:search-service', 3600)
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
    let(:window_start) { 10.minutes.ago }

    before do
      allow(redis).to receive(:get).with('chaos_window:file-service').and_return(window_start.to_i.to_s)
    end

    it 'does not resolve incidents or clear flags for an unauthenticated caller' do
      incident = alert_incident('file-service')
      delete :reset

      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:keys)
      expect(redis).not_to have_received(:del)
      expect(incident.reload.status).to eq('open')
    end

    it 'does not resolve incidents or clear flags for a non-admin user' do
      incident = alert_incident('file-service')
      set_jwt_env(request, role: 'user')
      delete :reset

      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:keys)
      expect(redis).not_to have_received(:del)
      expect(incident.reload.status).to eq('open')
    end

    it 'clears flags and resolves only alert incidents opened during the chaos window' do
      allow(redis).to receive(:keys).with('chaos:*').and_return(['chaos:file-service:upload_s3_error'])
      chaos = alert_incident('file-service')
      before_window = alert_incident('file-service', created_at: window_start - 5.minutes)
      human_filed = open_incident('file-service', reporter_id: SecureRandom.uuid)
      manual = open_incident('file-service')
      no_window = alert_incident('search-service')

      set_jwt_env(request, role: 'admin')
      delete :reset

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:del).with('chaos:file-service:upload_s3_error')
      expect(redis).to have_received(:del).with('chaos_window:file-service')
      expect(response.parsed_body['resolved_incidents']).to eq([chaos.id])
      expect(chaos.reload.status).to eq('resolved')
      [before_window, human_filed, manual, no_window].each do |incident|
        expect(incident.reload.status).to eq('open')
      end
    end
  end
end
