require 'rails_helper'

RSpec.describe Api::V1::Admin::AnnouncementsController do
  before { set_jwt_env(request) }

  describe 'GET #show' do
    it 'renders the announcement' do
      announcement = create(:announcement, :published)

      get :show, params: { id: announcement.id }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)).to include('id' => announcement.id, 'status' => 'published')
    end
  end

  describe 'PUT #update' do
    it 'returns 422 when the update is invalid' do
      announcement = create(:announcement, title: 'Original')

      put :update, params: { id: announcement.id, announcement: { title: '', severity: 'apocalyptic' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to include("Title can't be blank")
      expect(announcement.reload.title).to eq('Original')
    end
  end
end
