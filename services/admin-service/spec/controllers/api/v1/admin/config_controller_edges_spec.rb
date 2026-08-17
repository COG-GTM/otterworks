require 'rails_helper'

RSpec.describe Api::V1::Admin::ConfigController do
  before { set_jwt_env(request) }

  describe 'GET #show' do
    it 'renders a single config entry' do
      config = create(:system_config, :integer_config)

      get :show, params: { id: config.id }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)).to include('id' => config.id, 'key' => config.key, 'value' => '42')
    end
  end

  describe 'PUT #update' do
    it 'returns 422 when the new value is invalid' do
      config = create(:system_config)

      put :update, params: { id: config.id, config: { value: '' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to include("Value can't be blank")
      expect(config.reload.value).to eq('some_value')
    end

    it 'masks secret values in the audit trail' do
      config = create(:system_config, :secret, value: 'old-secret')

      put :update, params: { id: config.id, config: { value: 'new-secret' } }

      expect(response).to have_http_status(:ok)
      changes = AuditLog.last.changes_made
      expect(changes).to include('before' => '********', 'after' => '********')
    end
  end
end
