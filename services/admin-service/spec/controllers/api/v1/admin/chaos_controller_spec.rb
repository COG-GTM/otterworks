require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis, setex: 'OK', keys: [], del: 0) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
  end

  around do |example|
    original = ENV.fetch('CHAOS_SECRET', nil)
    ENV.delete('CHAOS_SECRET')
    example.run
  ensure
    original.nil? ? ENV.delete('CHAOS_SECRET') : ENV.store('CHAOS_SECRET', original)
  end

  def open_incident
    Incident.create!(title: 'Search 500s', description: 'suggest failing',
                     severity: 'high', status: 'open', affected_service: 'search-service')
  end

  describe 'POST #trigger' do
    let(:params) { { service: 'search-service', scenario: 'suggest_500' } }

    it 'rejects a caller with no JWT identity even when CHAOS_SECRET is unset' do
      post :trigger, params: params
      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
      expect(ChaosProbeService).not_to have_received(:start)
    end

    %w[user viewer editor].each do |role|
      it "rejects a #{role} JWT even when CHAOS_SECRET is unset" do
        set_jwt_env(request, role: role)
        post :trigger, params: params
        expect(response).to have_http_status(:forbidden)
        expect(redis).not_to have_received(:setex)
      end
    end

    it 'lets an admin trigger chaos when CHAOS_SECRET is unset' do
      set_jwt_env(request, role: 'admin')
      post :trigger, params: params
      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:setex).with('chaos:search-service:suggest_500', 600, '1')
    end

    it 'rejects a correct X-Chaos-Secret without an admin JWT' do
      ENV['CHAOS_SECRET'] = 's3cret'
      set_jwt_env(request, role: 'user')
      request.headers['X-Chaos-Secret'] = 's3cret'
      post :trigger, params: params
      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
    end

    it 'requires the secret in addition to the admin JWT when CHAOS_SECRET is set' do
      ENV['CHAOS_SECRET'] = 's3cret'
      set_jwt_env(request, role: 'admin')
      post :trigger, params: params
      expect(response).to have_http_status(:unauthorized)

      request.headers['X-Chaos-Secret'] = 's3cret'
      post :trigger, params: params
      expect(response).to have_http_status(:ok)
    end
  end

  describe 'DELETE #reset' do
    it 'does not resolve incidents for a non-admin JWT' do
      incident = open_incident
      set_jwt_env(request, role: 'user')
      delete :reset
      expect(response).to have_http_status(:forbidden)
      expect(incident.reload.status).to eq('open')
      expect(redis).not_to have_received(:keys)
    end

    it 'clears flags and resolves chaos incidents for an admin' do
      incident = open_incident
      allow(redis).to receive(:keys).with('chaos:*').and_return(['chaos:search-service:suggest_500'])
      set_jwt_env(request, role: 'super_admin')
      delete :reset
      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:del).with('chaos:search-service:suggest_500')
      expect(incident.reload.status).to eq('resolved')
    end
  end
end
