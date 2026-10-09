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

    it 'lets a non-admin read their own quota' do
      set_jwt_env(request, user_id: user_id, role: 'user')
      get :show, params: { user_id: user_id.upcase }
      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['user_id']).to eq(user_id)
    end

    it "forbids a non-admin from reading another user's quota" do
      set_jwt_env(request, role: 'user')
      get :show, params: { user_id: user_id }
      expect(response).to have_http_status(:forbidden)
      expect(response.body).not_to include('quota_bytes')
    end

    it 'returns 403, not 404, to a non-admin probing an unknown user id' do
      set_jwt_env(request, role: 'user')
      get :show, params: { user_id: SecureRandom.uuid }
      expect(response).to have_http_status(:forbidden)
    end

    it 'forbids a caller with no user id from reading quotas' do
      set_jwt_env(request, user_id: nil, role: 'user')
      get :show, params: { user_id: user_id }
      expect(response).to have_http_status(:forbidden)
    end
  end

  describe 'PUT #update' do
    it 'forbids a non-admin from updating even their own quota' do
      set_jwt_env(request, user_id: user_id, role: 'user')
      put :update, params: { user_id: user_id, quota: { tier: 'enterprise' } }
      expect(response).to have_http_status(:forbidden)
      expect(quota.reload.tier).to eq('free')
    end

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
