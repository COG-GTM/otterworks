require 'rails_helper'

RSpec.describe Api::V1::Admin::BulkController do
  before { set_jwt_env(request) }

  describe 'POST #users' do
    it 'returns 400 when user_ids is not a non-empty array' do
      post :users, params: { operation: 'suspend', user_ids: 'not-an-array' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('user_ids must be a non-empty array')
    end

    it 'returns 400 when the operation is unknown' do
      post :users, params: { operation: 'teleport', user_ids: [SecureRandom.uuid] }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['errors']).to eq(['Invalid operation: teleport'])
    end

    it 'returns 422 when every user fails' do
      post :users, params: { operation: 'suspend', user_ids: [SecureRandom.uuid, SecureRandom.uuid] }

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['success_count']).to eq(0)
      expect(body['failure_count']).to eq(2)
    end

    it 'returns 207 when some users succeed and some fail' do
      user = create(:admin_user)

      post :users, params: { operation: 'suspend', user_ids: [user.id, SecureRandom.uuid] }

      expect(response).to have_http_status(:multi_status)
      body = JSON.parse(response.body)
      expect(body['success_count']).to eq(1)
      expect(body['failure_count']).to eq(1)
      expect(user.reload.status).to eq('suspended')
    end
  end
end
