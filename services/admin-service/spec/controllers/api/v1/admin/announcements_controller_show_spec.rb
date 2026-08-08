require 'rails_helper'

# Complements spec/controllers/api/v1/admin/announcements_controller_spec.rb by
# covering the show action and the validation-failure branch of update.
RSpec.describe Api::V1::Admin::AnnouncementsController do
  before { set_jwt_env(request) }

  let(:announcement) { create(:announcement) }

  describe 'GET #index filters' do
    let!(:published_critical) { create(:announcement, :published, :critical) }

    it 'filters by status' do
      create(:announcement)

      get :index, params: { status: 'published' }

      expect(JSON.parse(response.body)['announcements'].map { |a| a['id'] }).to eq([published_critical.id])
    end

    it 'filters by severity' do
      create(:announcement)

      get :index, params: { severity: 'critical' }

      expect(JSON.parse(response.body)['announcements'].map { |a| a['id'] }).to eq([published_critical.id])
    end
  end

  describe 'GET #show' do
    it 'returns the announcement' do
      get :show, params: { id: announcement.id }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['title']).to eq(announcement.title)
    end
  end

  describe 'PUT #update with an invalid payload' do
    it 'returns 422 and leaves the announcement untouched' do
      put :update, params: { id: announcement.id, announcement: { severity: 'apocalyptic' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details'].join).to match(/Severity/)
      expect(announcement.reload.severity).to eq('info')
    end
  end
end
