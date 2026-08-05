require 'rails_helper'

RSpec.describe Api::V1::Admin::FeaturesController do
  before { set_jwt_env(request) }

  describe 'GET #index' do
    it 'filters to disabled flags' do
      disabled = create(:feature_flag, enabled: false)
      create(:feature_flag, :enabled)

      get :index, params: { enabled: 'false' }

      expect(JSON.parse(response.body)['features'].map { |f| f['id'] }).to eq([disabled.id])
    end
  end

  describe 'PUT #update' do
    it 'rejects an invalid name and leaves the flag untouched' do
      flag = create(:feature_flag, name: 'good_name')

      expect { put :update, params: { id: flag.id, feature: { name: 'Bad Name' } } }.not_to change(AuditLog, :count)

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to include('Name must be snake_case')
      expect(flag.reload.name).to eq('good_name')
    end
  end
end
