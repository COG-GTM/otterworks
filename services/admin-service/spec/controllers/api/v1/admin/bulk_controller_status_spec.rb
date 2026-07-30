require 'rails_helper'

# Complements spec/controllers/api/v1/admin/bulk_controller_spec.rb by covering
# the HTTP status mapping for partial and total failures.
RSpec.describe Api::V1::Admin::BulkController do
  before { set_jwt_env(request) }

  it 'returns 400 when user_ids is not an array' do
    post :users, params: { operation: 'suspend', user_ids: 'not-an-array' }

    expect(response).to have_http_status(:bad_request)
    expect(JSON.parse(response.body)['error']).to eq('user_ids must be a non-empty array')
  end

  it 'returns 400 for an unknown operation' do
    post :users, params: { operation: 'explode', user_ids: [SecureRandom.uuid] }

    expect(response).to have_http_status(:bad_request)
    expect(JSON.parse(response.body)['errors']).to include('Invalid operation: explode')
  end

  it 'returns 422 when every user is missing' do
    post :users, params: { operation: 'suspend', user_ids: [SecureRandom.uuid, SecureRandom.uuid] }

    expect(response).to have_http_status(:unprocessable_entity)
    body = JSON.parse(response.body)
    expect(body['success_count']).to eq(0)
    expect(body['failure_count']).to eq(2)
  end

  it 'returns 207 when some users succeed and some fail' do
    user = create(:admin_user)

    post :users, params: { operation: 'suspend', user_ids: [user.id, SecureRandom.uuid], reason: 'spam' }

    expect(response).to have_http_status(:multi_status)
    body = JSON.parse(response.body)
    expect(body['success_count']).to eq(1)
    expect(body['failure_count']).to eq(1)
    expect(user.reload.suspended_reason).to eq('spam')
  end
end
