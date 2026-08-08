require 'rails_helper'

RSpec.describe ApplicationController do
  controller do
    def boom
      raise 'something exploded'
    end

    def invalid_record
      record = AdminUser.new
      record.validate
      raise ActiveRecord::RecordInvalid, record
    end

    def missing_param
      params.require(:widget)
      head :ok
    end

    def identity
      render json: { id: current_user_id, email: current_user_email, role: current_user_role,
                     metadata: @request_metadata }
    end
  end

  before do
    routes.draw do
      get 'boom' => 'anonymous#boom'
      get 'invalid_record' => 'anonymous#invalid_record'
      get 'missing_param' => 'anonymous#missing_param'
      get 'identity' => 'anonymous#identity'
    end
  end

  describe 'error handling' do
    it 'renders a generic 500 and logs unhandled errors' do
      allow(Rails.logger).to receive(:error)

      get :boom

      expect(response).to have_http_status(:internal_server_error)
      expect(JSON.parse(response.body)).to eq('error' => 'Internal server error')
      expect(Rails.logger).to have_received(:error).with('Unhandled error: something exploded')
    end

    it 'renders 422 with the validation details for an invalid record' do
      get :invalid_record

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['error']).to match(/Validation failed/)
      expect(body['details']).to include("Email can't be blank")
    end

    it 'renders 400 naming the missing parameter' do
      get :missing_param

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)).to eq('error' => 'Missing parameter: widget')
    end
  end

  describe 'request context' do
    it 'exposes the JWT claims and captures request metadata' do
      set_jwt_env(request, user_id: 'user-42', email: 'ops@otterworks.com', role: 'editor')
      request.headers['User-Agent'] = 'rspec-agent'

      get :identity

      expect(JSON.parse(response.body)).to include(
        'id' => 'user-42',
        'email' => 'ops@otterworks.com',
        'role' => 'editor'
      )
      expect(JSON.parse(response.body)['metadata']).to include('user_agent' => 'rspec-agent')
    end
  end
end
