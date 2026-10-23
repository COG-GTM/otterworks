require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis, setex: 'OK', keys: [], del: 0) }
  let(:trigger_params) { { service: 'search-service', scenario: 'suggest_500' } }

  around do |example|
    original = ENV.fetch('CHAOS_SECRET', nil)
    ENV.delete('CHAOS_SECRET')
    example.run
  ensure
    ENV['CHAOS_SECRET'] = original
  end

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
  end

  describe 'POST #trigger' do
    it 'rejects callers without an admin role' do
      set_jwt_env(request, role: 'user')
      post :trigger, params: trigger_params
      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
    end

    it 'rejects unauthenticated callers even when CHAOS_SECRET is unset' do
      post :trigger, params: trigger_params
      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
    end

    it 'lets an admin trigger chaos' do
      set_jwt_env(request, role: 'admin')
      post :trigger, params: trigger_params
      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:setex).with('chaos:search-service:suggest_500', 600, '1')
    end

    context 'when CHAOS_SECRET is configured' do
      before { ENV['CHAOS_SECRET'] = 'test-chaos-secret' }

      it 'requires the X-Chaos-Secret header in addition to the admin role' do
        set_jwt_env(request, role: 'admin')
        post :trigger, params: trigger_params
        expect(response).to have_http_status(:unauthorized)
        expect(redis).not_to have_received(:setex)
      end

      it 'does not let the secret stand in for the admin role' do
        set_jwt_env(request, role: 'user')
        request.headers['X-Chaos-Secret'] = 'test-chaos-secret'
        post :trigger, params: trigger_params
        expect(response).to have_http_status(:forbidden)
      end

      it 'accepts an admin with the matching secret' do
        set_jwt_env(request, role: 'admin')
        request.headers['X-Chaos-Secret'] = 'test-chaos-secret'
        post :trigger, params: trigger_params
        expect(response).to have_http_status(:ok)
      end
    end
  end

  describe 'DELETE #reset' do
    let!(:incident) do
      Incident.create!(title: 'Real outage', description: 'outage', severity: 'high', status: 'open',
                       affected_service: 'search-service')
    end

    it 'does not let a non-admin resolve open incidents' do
      set_jwt_env(request, role: 'user')
      delete :reset
      expect(response).to have_http_status(:forbidden)
      expect(incident.reload.status).to eq('open')
    end

    it 'lets an admin reset chaos and resolve incidents' do
      set_jwt_env(request, role: 'admin')
      delete :reset
      expect(response).to have_http_status(:ok)
      expect(incident.reload.status).to eq('resolved')
    end
  end
end
