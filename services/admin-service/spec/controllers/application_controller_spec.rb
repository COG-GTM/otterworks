require 'rails_helper'

RSpec.describe ApplicationController do
  controller do
    def whoami
      render json: { id: current_user_id, email: current_user_email, role: current_user_role,
                     metadata: @request_metadata }
    end

    def boom
      raise StandardError, 'kaboom'
    end

    def invalid
      record = AdminUser.new
      record.validate
      raise ActiveRecord::RecordInvalid, record
    end

    def missing
      params.require(:thing)
      head :ok
    end
  end

  before do
    routes.draw do
      get 'whoami' => 'anonymous#whoami'
      get 'boom' => 'anonymous#boom'
      get 'invalid' => 'anonymous#invalid'
      get 'missing' => 'anonymous#missing'
    end
  end

  describe 'JWT accessors and request metadata' do
    it 'exposes the caller identity and captures request metadata' do
      set_jwt_env(request, user_id: 'user-9', email: 'ops@otterworks.com', role: 'admin')
      request.headers['User-Agent'] = 'rspec-agent'

      get :whoami

      body = JSON.parse(response.body)
      expect(body).to include('id' => 'user-9', 'email' => 'ops@otterworks.com', 'role' => 'admin')
      expect(body['metadata']).to include('user_agent' => 'rspec-agent')
      expect(body['metadata']['ip_address']).to be_present
    end
  end

  describe 'error handling' do
    it 'renders 500 and logs unhandled errors' do
      allow(Rails.logger).to receive(:error)

      get :boom

      expect(response).to have_http_status(:internal_server_error)
      expect(JSON.parse(response.body)['error']).to eq('Internal server error')
      expect(Rails.logger).to have_received(:error).with(/kaboom/)
    end

    it 'renders 422 with the failed validations' do
      get :invalid

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to include(/Email/)
    end

    it 'renders 400 when a required parameter is missing' do
      get :missing

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Missing parameter: thing')
    end
  end
end
