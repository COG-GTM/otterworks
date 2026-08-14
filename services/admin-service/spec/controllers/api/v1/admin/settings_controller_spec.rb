require 'rails_helper'

RSpec.describe Api::V1::Admin::SettingsController do
  before { set_jwt_env(request) }

  describe 'GET #auto_investigate' do
    it 'reports the flag from AdminSettingsService' do
      allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(false)

      get :auto_investigate

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)).to eq('enabled' => false)
    end
  end

  describe 'PUT #update_auto_investigate' do
    before { allow(AdminSettingsService).to receive(:set_auto_investigate) }

    it 'persists the parsed boolean and echoes the stored value' do
      allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)

      put :update_auto_investigate, params: { enabled: 'true' }

      expect(response).to have_http_status(:ok)
      expect(AdminSettingsService).to have_received(:set_auto_investigate).with(true)
      expect(JSON.parse(response.body)).to eq('enabled' => true)
    end

    it 'accepts a false value' do
      allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(false)

      put :update_auto_investigate, params: { enabled: 'false' }

      expect(AdminSettingsService).to have_received(:set_auto_investigate).with(false)
    end

    it 'returns 400 when enabled is missing' do
      put :update_auto_investigate

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to match(/enabled/)
      expect(AdminSettingsService).not_to have_received(:set_auto_investigate)
    end
  end
end
