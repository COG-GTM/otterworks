require 'rails_helper'

# Complements spec/controllers/api/v1/admin/features_controller_spec.rb by
# covering the validation-failure branch of update.
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

  describe 'PUT #update with an invalid payload' do
    it 'returns 422 and leaves the flag untouched' do
      flag = create(:feature_flag, rollout_percentage: 10)

      put :update, params: { id: flag.id, feature: { rollout_percentage: 150 } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details'].join).to match(/Rollout percentage/)
      expect(flag.reload.rollout_percentage).to eq(10)
    end
  end
end
