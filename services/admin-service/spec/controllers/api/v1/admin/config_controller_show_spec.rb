require 'rails_helper'

# Complements spec/controllers/api/v1/admin/config_controller_spec.rb with #show,
# the audit trail and the validation failure path.
RSpec.describe Api::V1::Admin::ConfigController do
  before { set_jwt_env(request) }

  describe 'GET #show' do
    it 'serializes a single config' do
      config = create(:system_config, :integer_config)

      get :show, params: { id: config.id }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)).to include('id' => config.id, 'key' => config.key, 'value' => '42')
    end

    it 'returns 404 for an unknown config' do
      get :show, params: { id: SecureRandom.uuid }

      expect(response).to have_http_status(:not_found)
    end
  end

  describe 'PUT #update' do
    it 'returns 422 with the validation details' do
      config = create(:system_config, value: 'keep-me')

      put :update, params: { id: config.id, config: { value: '' } }

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['error']).to eq('Validation failed')
      expect(body['details']).to include("Value can't be blank")
      expect(config.reload.value).to eq('keep-me')
    end

    it 'masks the value of a secret config in the audit trail' do
      config = create(:system_config, :secret, value: 'old-secret')

      put :update, params: { id: config.id, config: { value: 'new-secret' } }

      expect(response).to have_http_status(:ok)
      expect(AuditLog.last.changes_made).to include('before' => '********', 'after' => '********')
    end
  end
end
