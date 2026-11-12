require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:chaos_secret) { 'test-chaos-secret-0123456789abcdef' }
  let(:redis) { instance_double(Redis, setex: 'OK', keys: [], del: 0) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('CHAOS_SECRET', '').and_return(chaos_secret)
  end

  def trigger_params
    { service: 'file-service', scenario: 'upload_s3_error' }
  end

  describe 'POST #trigger' do
    it 'sets the chaos flag for an admin with the correct secret' do
      set_jwt_env(request, role: 'admin')
      request.headers['X-Chaos-Secret'] = chaos_secret

      post :trigger, params: trigger_params

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:setex).with('chaos:file-service:upload_s3_error', 600, '1')
      expect(ChaosProbeService).to have_received(:start)
    end

    it 'rejects a non-admin user even with the correct secret' do
      set_jwt_env(request, role: 'user')
      request.headers['X-Chaos-Secret'] = chaos_secret

      post :trigger, params: trigger_params

      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
      expect(ChaosProbeService).not_to have_received(:start)
    end

    it 'rejects a request with no JWT role at all' do
      request.headers['X-Chaos-Secret'] = chaos_secret

      post :trigger, params: trigger_params

      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
    end

    it 'rejects an admin without the X-Chaos-Secret header' do
      set_jwt_env(request, role: 'admin')

      post :trigger, params: trigger_params

      expect(response).to have_http_status(:forbidden)
      expect(response.parsed_body['code']).to eq('chaos_secret_required')
      expect(redis).not_to have_received(:setex)
    end

    it 'rejects an admin with the wrong secret' do
      set_jwt_env(request, role: 'admin')
      request.headers['X-Chaos-Secret'] = 'wrong'

      post :trigger, params: trigger_params

      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
    end

    ['', '   '].each do |unset|
      it "fails closed when CHAOS_SECRET is #{unset.inspect}" do
        allow(ENV).to receive(:fetch).with('CHAOS_SECRET', '').and_return(unset)
        set_jwt_env(request, role: 'admin')
        request.headers['X-Chaos-Secret'] = unset

        post :trigger, params: trigger_params

        expect(response).to have_http_status(:service_unavailable)
        expect(response.parsed_body['code']).to eq('chaos_disabled')
        expect(redis).not_to have_received(:setex)
        expect(ChaosProbeService).not_to have_received(:start)
      end
    end
  end

  describe 'DELETE #reset' do
    let!(:incident) do
      Incident.create!(title: 'Uploads failing', description: 'S3 errors', severity: 'critical',
                       affected_service: 'file-service', status: 'open')
    end

    it 'does not resolve incidents for a non-admin user' do
      set_jwt_env(request, role: 'user')
      request.headers['X-Chaos-Secret'] = chaos_secret

      delete :reset

      expect(response).to have_http_status(:forbidden)
      expect(incident.reload.status).to eq('open')
    end

    it 'does not resolve incidents when CHAOS_SECRET is unset' do
      allow(ENV).to receive(:fetch).with('CHAOS_SECRET', '').and_return('')
      set_jwt_env(request, role: 'admin')

      delete :reset

      expect(response).to have_http_status(:service_unavailable)
      expect(incident.reload.status).to eq('open')
    end

    it 'clears flags and resolves incidents for an admin with the secret' do
      allow(redis).to receive(:keys).with('chaos:*').and_return(['chaos:file-service:upload_s3_error'])
      set_jwt_env(request, role: 'admin')
      request.headers['X-Chaos-Secret'] = chaos_secret

      delete :reset

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:del).with('chaos:file-service:upload_s3_error')
      expect(incident.reload.status).to eq('resolved')
    end
  end
end
