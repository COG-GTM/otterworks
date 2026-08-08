require 'rails_helper'

# Complements spec/controllers/api/v1/admin/features_controller_spec.rb with the
# update validation failure path.
RSpec.describe Api::V1::Admin::FeaturesController do
  before { set_jwt_env(request) }

  describe 'GET #index' do
    it 'filters to disabled flags' do
      enabled = create(:feature_flag, :enabled)
      disabled = create(:feature_flag)

      get :index, params: { enabled: 'false' }

      ids = JSON.parse(response.body)['features'].map { |f| f['id'] }
      expect(ids).to eq([disabled.id])
      expect(ids).not_to include(enabled.id)
    end
  end

  describe 'PUT #update' do
    it 'returns 422 when the new name is not snake_case' do
      flag = create(:feature_flag, name: 'good_name')

      put :update, params: { id: flag.id, feature: { name: 'Bad Name' } }

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['error']).to eq('Validation failed')
      expect(body['details']).to include('Name must be snake_case')
      expect(flag.reload.name).to eq('good_name')
    end

    it 'returns 422 for an out-of-range rollout percentage' do
      flag = create(:feature_flag)

      put :update, params: { id: flag.id, feature: { rollout_percentage: 150 } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details'].join).to match(/Rollout percentage/)
    end
  end
end
