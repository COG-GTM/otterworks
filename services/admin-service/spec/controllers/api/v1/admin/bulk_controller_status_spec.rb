require 'rails_helper'

RSpec.describe Api::V1::Admin::BulkController do
  before { set_jwt_env(request) }

  describe 'POST #users status mapping' do
    it 'rejects a scalar user_ids value' do
      post :users, params: { operation: 'suspend', user_ids: 'not-an-array' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('user_ids must be a non-empty array')
    end

    it 'returns 400 for an unsupported operation' do
      user = create(:admin_user)

      post :users, params: { operation: 'teleport', user_ids: [user.id] }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['errors']).to eq(['Invalid operation: teleport'])
      expect(user.reload.status).to eq('active')
    end

    it 'returns 422 when every target fails' do
      post :users, params: { operation: 'suspend', user_ids: [SecureRandom.uuid, SecureRandom.uuid] }

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['success_count']).to eq(0)
      expect(body['failure_count']).to eq(2)
    end

    it 'returns 400 when the operation parameter is missing' do
      post :users, params: { user_ids: [SecureRandom.uuid] }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Missing parameter: operation')
    end
  end
end
