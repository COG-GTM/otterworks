require 'rails_helper'

RSpec.describe Api::V1::Admin::QuotasController do
  before { set_jwt_env(request) }

  let(:user_id) { SecureRandom.uuid }
  let!(:quota) { create(:storage_quota, user_id: user_id) }

  describe 'GET #show' do
    it 'returns the storage quota for a user' do
      get :show, params: { user_id: user_id }
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['user_id']).to eq(user_id)
      expect(body['tier']).to eq('free')
    end

    it 'returns 404 for unknown user' do
      get :show, params: { user_id: SecureRandom.uuid }
      expect(response).to have_http_status(:not_found)
    end
  end

  describe 'authorization' do
    it 'forbids non-admin roles from viewing a quota' do
      set_jwt_env(request, role: 'support')
      get :show, params: { user_id: user_id }
      expect(response).to have_http_status(:forbidden)
    end

    it 'forbids non-admin roles from updating a quota' do
      set_jwt_env(request, role: 'support')
      patch :update, params: { user_id: user_id, quota: { quota_bytes: 1 } }
      expect(response).to have_http_status(:forbidden)
    end
  end

  describe 'PATCH #update' do
    it 'updates the quota and syncs it to auth-service' do
      expect(AuthServiceClient).to receive(:update_quota)
        .with(hash_including(user_id: user_id, quota_bytes: 21_474_836_480))
        .and_return(true)

      patch :update, params: { user_id: user_id, quota: { quota_bytes: 21_474_836_480 } }
      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['quota_bytes']).to eq(21_474_836_480)
    end
  end

  describe 'PUT #update' do
    before { allow(AuthServiceClient).to receive(:update_quota).and_return(true) }

    it 'updates the quota' do
      put :update, params: { user_id: user_id, quota: { tier: 'pro', quota_bytes: 214_748_364_800 } }
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['tier']).to eq('pro')
    end

    it 'returns errors for invalid params' do
      put :update, params: { user_id: user_id, quota: { tier: 'invalid' } }
      expect(response).to have_http_status(:unprocessable_entity)
    end
  end
end
