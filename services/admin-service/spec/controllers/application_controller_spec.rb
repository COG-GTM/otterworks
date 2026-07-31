require 'rails_helper'

RSpec.describe ApplicationController do
  controller do
    def index
      render json: {
        user_id: current_user_id,
        email: current_user_email,
        role: current_user_role,
        metadata: @request_metadata
      }
    end

    def show
      raise ActiveRecord::RecordNotFound
    end

    def create
      raise StandardError, 'something exploded'
    end

    def update
      user = AdminUser.new
      user.validate
      raise ActiveRecord::RecordInvalid, user
    end

    def destroy
      raise ActionController::ParameterMissing, :announcement
    end
  end

  describe 'request metadata and JWT accessors' do
    it 'exposes the JWT claims and captures the client metadata' do
      set_jwt_env(request, user_id: 'user-1', email: 'ops@otterworks.com', role: 'editor')
      request.user_agent = 'RSpec Agent'

      get :index

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body).to include('user_id' => 'user-1', 'email' => 'ops@otterworks.com', 'role' => 'editor')
      expect(body['metadata']).to include('user_agent' => 'RSpec Agent')
      expect(body['metadata']['ip_address']).to be_present
    end
  end

  describe 'error handling' do
    it 'renders 500 and logs unhandled errors' do
      allow(Rails.logger).to receive(:error)

      post :create

      expect(response).to have_http_status(:internal_server_error)
      expect(JSON.parse(response.body)).to eq('error' => 'Internal server error')
      expect(Rails.logger).to have_received(:error).with('Unhandled error: something exploded')
    end

    it 'renders 404 for a missing record' do
      get :show, params: { id: '1' }

      expect(response).to have_http_status(:not_found)
      expect(JSON.parse(response.body)).to eq('error' => 'Resource not found')
    end

    it 'renders 422 with validation details' do
      put :update, params: { id: '1' }

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['error']).to match(/Validation failed/)
      expect(body['details']).to include("Email can't be blank")
    end

    it 'renders 400 for a missing parameter' do
      delete :destroy, params: { id: '1' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)).to eq('error' => 'Missing parameter: announcement')
    end
  end
end
