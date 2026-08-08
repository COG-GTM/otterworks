require 'rails_helper'

# Complements spec/controllers/api/v1/admin/announcements_controller_spec.rb with
# #show and the update validation failure path.
RSpec.describe Api::V1::Admin::AnnouncementsController do
  before { set_jwt_env(request) }

  describe 'GET #index filters' do
    let!(:critical) { create(:announcement, :published, :critical) }
    let!(:draft) { create(:announcement) }

    def body_ids
      JSON.parse(response.body)['announcements'].map { |a| a['id'] }
    end

    it 'filters by severity' do
      get :index, params: { severity: 'critical' }

      expect(body_ids).to eq([critical.id])
    end

    it 'filters to currently active announcements' do
      create(:announcement, :expired)

      get :index, params: { active: 'true' }

      expect(body_ids).to eq([critical.id])
      expect(body_ids).not_to include(draft.id)
    end
  end

  describe 'GET #show' do
    it 'serializes a single announcement' do
      announcement = create(:announcement, :published, :critical)

      get :show, params: { id: announcement.id }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)).to include('id' => announcement.id, 'title' => announcement.title,
                                                   'severity' => 'critical', 'status' => 'published')
    end

    it 'returns 404 for an unknown announcement' do
      get :show, params: { id: SecureRandom.uuid }

      expect(response).to have_http_status(:not_found)
    end
  end

  describe 'PUT #update' do
    it 'returns 422 with the validation details' do
      announcement = create(:announcement, title: 'Keep me')

      put :update, params: { id: announcement.id, announcement: { title: '' } }

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['error']).to eq('Validation failed')
      expect(body['details']).to include("Title can't be blank")
      expect(announcement.reload.title).to eq('Keep me')
    end
  end
end
