require 'rails_helper'

# Complements spec/controllers/api/v1/admin/bulk_controller_spec.rb with the
# rejected payloads and the non-2xx status mapping.
RSpec.describe Api::V1::Admin::BulkController do
  before { set_jwt_env(request) }

  describe 'POST #users' do
    it 'returns 400 when user_ids is not an array' do
      post :users, params: { operation: 'suspend', user_ids: 'not-an-array' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('user_ids must be a non-empty array')
    end

    it 'returns 400 when the operation is unknown' do
      user = create(:admin_user)

      post :users, params: { operation: 'teleport', user_ids: [user.id] }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['errors']).to eq(['Invalid operation: teleport'])
    end

    it 'returns 400 when the operation is missing' do
      post :users, params: { user_ids: [SecureRandom.uuid] }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Missing parameter: operation')
    end

    it 'returns 422 when every user fails' do
      post :users, params: { operation: 'suspend', user_ids: [SecureRandom.uuid, SecureRandom.uuid] }

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body).to include('success_count' => 0, 'failure_count' => 2)
      expect(body['errors'].first['error']).to eq('2 user(s) not found')
    end

    it 'returns 207 when some users succeed and some fail' do
      user = create(:admin_user)

      post :users, params: { operation: 'suspend', user_ids: [user.id, SecureRandom.uuid], reason: 'cleanup' }

      expect(response).to have_http_status(:multi_status)
      expect(JSON.parse(response.body)).to include('success_count' => 1, 'failure_count' => 1)
      expect(user.reload).to have_attributes(status: 'suspended', suspended_reason: 'cleanup')
    end
  end
end
