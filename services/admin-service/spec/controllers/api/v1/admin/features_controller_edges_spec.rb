require 'rails_helper'

RSpec.describe Api::V1::Admin::FeaturesController do
  before { set_jwt_env(request) }

  describe 'PUT #update' do
    it 'returns 422 when the update is invalid' do
      flag = create(:feature_flag, name: 'valid_flag')

      put :update, params: { id: flag.id, feature: { name: 'Not Snake Case' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to include('Name must be snake_case')
      expect(flag.reload.name).to eq('valid_flag')
    end
  end
end
