require 'rails_helper'

RSpec.describe Api::V1::Admin::FeaturesController do
  before { set_jwt_env(request) }

  describe 'GET #index' do
    let!(:enabled_flag) { create(:feature_flag, :enabled, target_users: [SecureRandom.uuid], target_groups: ['beta']) }
    let!(:disabled_flag) { create(:feature_flag) }

    %w[user viewer].each do |role|
      it "forbids flag listings for the #{role} role" do
        set_jwt_env(request, role: role)
        get :index
        expect(response).to have_http_status(:forbidden)
        expect(response.body).not_to include(enabled_flag.target_users.first)
        expect(response.body).not_to include('beta')
      end
    end

    it 'forbids flag listings when no role is present' do
      request.env.delete('jwt.user_role')
      get :index
      expect(response).to have_http_status(:forbidden)
    end

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
    let(:flag) { create(:feature_flag, target_users: [SecureRandom.uuid], target_groups: ['beta']) }

    it 'forbids flag details for non-admin roles' do
      set_jwt_env(request, role: 'user')
      get :show, params: { id: flag.id }
      expect(response).to have_http_status(:forbidden)
      expect(response.body).not_to include(flag.target_users.first)
    end

    it 'does not reveal whether a flag exists to non-admin roles' do
      set_jwt_env(request, role: 'user')
      get :show, params: { id: SecureRandom.uuid }
      expect(response).to have_http_status(:forbidden)
    end

    %w[admin owner].each do |role|
      it "returns the flag to the #{role} role" do
        set_jwt_env(request, role: role)
        get :show, params: { id: flag.id }
        expect(response).to have_http_status(:ok)
        expect(JSON.parse(response.body)['target_groups']).to eq(['beta'])
      end
    end

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

    it 'forbids updates for non-admin roles' do
      set_jwt_env(request, role: 'user')
      put :update, params: { id: flag.id, feature: { enabled: true } }
      expect(response).to have_http_status(:forbidden)
      expect(flag.reload.enabled).to be false
    end

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
end
