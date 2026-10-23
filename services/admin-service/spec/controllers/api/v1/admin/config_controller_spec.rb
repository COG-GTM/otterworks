require 'rails_helper'

RSpec.describe Api::V1::Admin::ConfigController do
  before { set_jwt_env(request) }

  describe 'GET #index' do
    let!(:public_config) { create(:system_config) }
    let!(:secret_config) { create(:system_config, :secret) }

    it 'returns only public configs' do
      get :index
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      keys = body['configs'].map { |c| c['id'] }
      expect(keys).to include(public_config.id)
      expect(keys).not_to include(secret_config.id)
    end
  end

  describe 'PUT #update' do
    let(:config) { create(:system_config, value: 'old_value') }

    it 'updates the config value' do
      put :update, params: { id: config.id, config: { value: 'new_value' } }
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['value']).to eq('new_value')
    end
  end

  describe 'role enforcement' do
    let(:config) { create(:system_config) }

    it 'forbids listing configs for non-admin roles' do
      set_jwt_env(request, role: 'user')
      get :index
      expect(response).to have_http_status(:forbidden)
    end

    it 'forbids reading a config for non-admin roles' do
      set_jwt_env(request, role: 'viewer')
      get :show, params: { id: config.id }
      expect(response).to have_http_status(:forbidden)
    end
  end
end
