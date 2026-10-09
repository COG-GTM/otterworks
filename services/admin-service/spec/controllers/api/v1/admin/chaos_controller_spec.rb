require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis, setex: 'OK', keys: [], del: 0) }
  let(:chaos_params) { { service: 'search-service', scenario: 'suggest_500' } }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return(nil)
  end

  describe 'without an admin JWT' do
    it 'rejects trigger when no user is authenticated, even with CHAOS_SECRET unset' do
      post :trigger, params: chaos_params
      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
    end

    it 'rejects reset for a non-admin user' do
      set_jwt_env(request, role: 'user')
      delete :reset
      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:keys)
    end
  end

  describe 'with an admin JWT' do
    before { set_jwt_env(request, role: 'admin') }

    it 'triggers chaos when CHAOS_SECRET is unset' do
      post :trigger, params: chaos_params
      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:setex).with('chaos:search-service:suggest_500', anything, '1')
    end

    it 'resets chaos' do
      delete :reset
      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['status']).to eq('reset')
    end

    context 'when CHAOS_SECRET is set' do
      before { allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return('chaos-s3cret') }

      it 'requires a matching X-Chaos-Secret header' do
        post :trigger, params: chaos_params
        expect(response).to have_http_status(:unauthorized)

        request.headers['X-Chaos-Secret'] = 'wrong'
        post :trigger, params: chaos_params
        expect(response).to have_http_status(:unauthorized)
        expect(redis).not_to have_received(:setex)
      end

      it 'accepts the matching X-Chaos-Secret header' do
        request.headers['X-Chaos-Secret'] = 'chaos-s3cret'
        post :trigger, params: chaos_params
        expect(response).to have_http_status(:ok)
      end
    end
  end
end
