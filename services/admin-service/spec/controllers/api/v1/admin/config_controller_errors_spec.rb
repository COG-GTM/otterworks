require 'rails_helper'

RSpec.describe Api::V1::Admin::ConfigController do
  before { set_jwt_env(request) }

  describe 'GET #show' do
    it 'renders a single config entry' do
      config = create(:system_config, key: 'retention_days', value: '30')

      get :show, params: { id: config.id }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)).to include('key' => 'retention_days', 'value' => '30')
    end

    it 'masks the value of a secret config' do
      config = create(:system_config, :secret)

      get :show, params: { id: config.id }

      expect(JSON.parse(response.body)['value']).to eq('********')
    end
  end

  describe 'PUT #update' do
    it 'rejects a blank value without auditing' do
      config = create(:system_config, value: 'keep-me')

      expect { put :update, params: { id: config.id, config: { value: '' } } }.not_to change(AuditLog, :count)

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to include("Value can't be blank")
      expect(config.reload.value).to eq('keep-me')
    end

    it 'masks both sides of the audit trail for a secret config' do
      config = create(:system_config, :secret, value: 'old-secret')

      put :update, params: { id: config.id, config: { value: 'new-secret' } }

      expect(response).to have_http_status(:ok)
      expect(AuditLog.last.changes_made).to include('before' => '********', 'after' => '********')
      expect(config.reload.value).to eq('new-secret')
    end
  end
end
