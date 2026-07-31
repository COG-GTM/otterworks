require 'rails_helper'

RSpec.describe Api::V1::Admin::AnnouncementsController do
  before { set_jwt_env(request) }

  describe 'GET #index filters' do
    let!(:critical) { create(:announcement, :published, :critical) }
    let!(:draft) { create(:announcement) }

    it 'filters by severity' do
      get :index, params: { severity: 'critical' }

      expect(JSON.parse(response.body)['announcements'].map { |a| a['id'] }).to eq([critical.id])
    end

    it 'returns only currently active announcements' do
      create(:announcement, :expired)

      get :index, params: { active: 'true' }

      expect(JSON.parse(response.body)['announcements'].map { |a| a['id'] }).to eq([critical.id])
    end

    it 'filters by status' do
      get :index, params: { status: 'draft' }

      expect(JSON.parse(response.body)['announcements'].map { |a| a['id'] }).to eq([draft.id])
    end
  end

  describe 'GET #show' do
    it 'renders the announcement with its computed active flag' do
      announcement = create(:announcement, :published, title: 'Maintenance window')

      get :show, params: { id: announcement.id }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)).to include('title' => 'Maintenance window', 'active' => true)
    end
  end

  describe 'PUT #update' do
    it 'rejects an invalid update and leaves the record untouched' do
      announcement = create(:announcement, title: 'Original')

      expect { put :update, params: { id: announcement.id, announcement: { title: '' } } }
        .not_to change(AuditLog, :count)

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to include("Title can't be blank")
      expect(announcement.reload.title).to eq('Original')
    end
  end
end
