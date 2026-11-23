require 'rails_helper'

RSpec.describe Api::V1::Admin::MetricsController do
  before { set_jwt_env(request) }

  describe 'GET #summary' do
    before do
      create_list(:admin_user, 2)
      create(:feature_flag, :enabled)
      create(:storage_quota)
    end

    it 'returns metrics summary' do
      get :summary
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body).to have_key('users')
      expect(body).to have_key('storage')
      expect(body).to have_key('features')
      expect(body).to have_key('announcements')
      expect(body).to have_key('audit')
      expect(body['users']['total']).to eq(2)
      expect(body['features']['enabled']).to eq(1)
    end
  end

  describe 'role enforcement' do
    it 'forbids the metrics summary for non-admin roles' do
      set_jwt_env(request, role: 'user')
      get :summary
      expect(response).to have_http_status(:forbidden)
    end
  end
end
