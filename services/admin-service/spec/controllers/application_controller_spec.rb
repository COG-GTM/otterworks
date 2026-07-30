require 'rails_helper'

RSpec.describe ApplicationController do
  controller do
    def index
      render json: { metadata: @request_metadata, user: { id: current_user_id, email: current_user_email,
                                                          role: current_user_role } }
    end

    def show
      case params[:kind]
      when 'not_found' then raise ActiveRecord::RecordNotFound
      when 'invalid'   then raise ActiveRecord::RecordInvalid, AdminUser.new.tap(&:validate)
      when 'missing'   then raise ActionController::ParameterMissing, :announcement
      else raise 'unexpected failure'
      end
    end

    def create
      render json: paginate(AdminUser.order(:created_at))
    end
  end

  before { set_jwt_env(request, user_id: 'user-9', email: 'nine@otterworks.com', role: 'admin') }

  describe 'request metadata and JWT accessors' do
    it 'exposes the caller identity and request metadata' do
      get :index

      body = JSON.parse(response.body)
      expect(body['user']).to eq('id' => 'user-9', 'email' => 'nine@otterworks.com', 'role' => 'admin')
      expect(body['metadata']).to include('ip_address' => '0.0.0.0')
    end
  end

  describe 'error handling' do
    it 'renders 404 for a missing record' do
      get :show, params: { id: 1, kind: 'not_found' }

      expect(response).to have_http_status(:not_found)
      expect(JSON.parse(response.body)['error']).to eq('Resource not found')
    end

    it 'renders 422 with validation details' do
      get :show, params: { id: 1, kind: 'invalid' }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to be_present
    end

    it 'renders 400 for a missing parameter' do
      get :show, params: { id: 1, kind: 'missing' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Missing parameter: announcement')
    end

    it 'renders 500 for an unhandled error' do
      allow(Rails.logger).to receive(:error)

      get :show, params: { id: 1, kind: 'other' }

      expect(response).to have_http_status(:internal_server_error)
      expect(JSON.parse(response.body)['error']).to eq('Internal server error')
      expect(Rails.logger).to have_received(:error).with(/unexpected failure/)
    end
  end

  describe '#paginate' do
    before { create_list(:admin_user, 3) }

    it 'defaults to the first page of twenty' do
      post :create

      expect(JSON.parse(response.body)).to include('total' => 3, 'page' => 1, 'per_page' => 20)
      expect(response.headers['X-Total-Count']).to eq('3')
      expect(response.headers['X-Page']).to eq('1')
      expect(response.headers['X-Per-Page']).to eq('20')
    end

    it 'clamps per_page to 100 and page to at least 1' do
      post :create, params: { page: 0, per_page: 500 }

      expect(JSON.parse(response.body)).to include('page' => 1, 'per_page' => 100)
    end

    it 'returns the requested slice' do
      post :create, params: { page: 2, per_page: 2 }

      body = JSON.parse(response.body)
      expect(body['records'].length).to eq(1)
      expect(body['page']).to eq(2)
    end
  end
end
