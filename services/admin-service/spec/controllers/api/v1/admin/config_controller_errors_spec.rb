require 'rails_helper'

# Complements spec/controllers/api/v1/admin/config_controller_spec.rb by
# covering the show action and the validation-failure branch of update.
RSpec.describe Api::V1::Admin::ConfigController do
  before { set_jwt_env(request) }

  let(:config) { create(:system_config) }

  describe 'GET #show' do
    it 'returns the config entry' do
      get :show, params: { id: config.id }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['key']).to eq(config.key)
    end
  end

  describe 'PUT #update' do
    it 'returns 422 when the new value is blank' do
      put :update, params: { id: config.id, config: { value: '' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to include("Value can't be blank")
      expect(config.reload.value).to eq('some_value')
    end

    it 'masks secret values in the audit trail' do
      secret = create(:system_config, :secret)

      put :update, params: { id: secret.id, config: { value: 'new-secret' } }

      expect(response).to have_http_status(:ok)
      expect(AuditLog.last.changes_made).to include('before' => '********', 'after' => '********')
    end
  end
end
