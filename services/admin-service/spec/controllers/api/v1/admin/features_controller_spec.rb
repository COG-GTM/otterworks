require 'rails_helper'

RSpec.describe Api::V1::Admin::FeaturesController do
  before { set_jwt_env(request) }

  describe 'GET #index' do
    let!(:enabled_flag) { create(:feature_flag, :enabled) }
    let!(:disabled_flag) { create(:feature_flag) }

    it 'returns all feature flags' do
      get :index
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['features'].length).to eq(2)
    end

    it 'filters by enabled status' do
      get :index, params: { enabled: 'true' }
      body = JSON.parse(response.body)
      expect(body['features'].all? { |f| f['enabled'] }).to be true
    end
  end

  describe 'GET #show' do
    let(:flag) { create(:feature_flag) }

    it 'returns the feature flag' do
      get :show, params: { id: flag.id }
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['name']).to eq(flag.name)
    end
  end

  describe 'POST #create' do
    let(:valid_params) do
      { feature: { name: 'new_feature', description: 'A new feature', enabled: true, rollout_percentage: 50 } }
    end

    it 'creates a new feature flag' do
      expect do
        post :create, params: valid_params
      end.to change(FeatureFlag, :count).by(1)
      expect(response).to have_http_status(:created)
    end

    it 'returns errors for invalid params' do
      post :create, params: { feature: { name: 'Invalid Name' } }
      expect(response).to have_http_status(:unprocessable_entity)
    end
  end

  describe 'PUT #update' do
    let(:flag) { create(:feature_flag) }

    it 'updates the feature flag' do
      put :update, params: { id: flag.id, feature: { enabled: true } }
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['enabled']).to be true
    end
  end

  describe 'DELETE #destroy' do
    let!(:flag) { create(:feature_flag) }

    it 'deletes the feature flag' do
      expect do
        delete :destroy, params: { id: flag.id }
      end.to change(FeatureFlag, :count).by(-1)
      expect(response).to have_http_status(:no_content)
    end
  end

  describe 'role enforcement' do
    let(:flag) { create(:feature_flag) }

    it 'forbids listing feature flags for non-admin roles' do
      set_jwt_env(request, role: 'user')
      get :index
      expect(response).to have_http_status(:forbidden)
    end

    it 'forbids reading a feature flag for non-admin roles' do
      set_jwt_env(request, role: 'user')
      get :show, params: { id: flag.id }
      expect(response).to have_http_status(:forbidden)
    end
  end
end
