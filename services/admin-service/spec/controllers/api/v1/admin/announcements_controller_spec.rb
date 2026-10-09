require 'rails_helper'

RSpec.describe Api::V1::Admin::AnnouncementsController do
  before { set_jwt_env(request) }

  describe 'GET #index' do
    let!(:announcements) { create_list(:announcement, 3) }

    it 'returns all announcements' do
      get :index
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['announcements'].length).to eq(3)
    end

    it 'filters by status' do
      create(:announcement, :published)
      get :index, params: { status: 'published' }
      body = JSON.parse(response.body)
      expect(body['announcements'].all? { |a| a['status'] == 'published' }).to be true
    end

    it 'lets an admin filter drafts' do
      create(:announcement, :published)
      get :index, params: { status: 'draft' }
      body = JSON.parse(response.body)
      expect(body['announcements'].length).to eq(3)
      expect(body['announcements'].all? { |a| a['status'] == 'draft' }).to be true
    end
  end

  describe 'GET #show' do
    let(:announcement) { create(:announcement) }

    it 'returns a draft announcement to an admin' do
      get :show, params: { id: announcement.id }
      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['id']).to eq(announcement.id)
    end
  end

  context 'when the caller is not an admin' do
    before { set_jwt_env(request, role: 'viewer') }

    let!(:active) { create(:announcement, :published) }
    let!(:draft) { create(:announcement) }
    let!(:archived) { create(:announcement, :archived) }
    let!(:expired) { create(:announcement, :expired) }
    let!(:scheduled) { create(:announcement, status: 'published', starts_at: 1.day.from_now) }

    describe 'GET #index' do
      it 'returns only active announcements' do
        get :index
        expect(response).to have_http_status(:ok)
        ids = JSON.parse(response.body)['announcements'].pluck('id')
        expect(ids).to eq([active.id])
      end

      it 'hides active announcements targeted at other roles' do
        everyone = create(:announcement, :published, target_audience: { 'role' => 'all' })
        viewers = create(:announcement, :published, target_audience: { 'role' => 'viewers' })
        create(:announcement, :published, target_audience: { 'role' => 'admins' })
        seeded = create(:announcement, :published, target_audience: { 'roles' => ['viewer'] })
        create(:announcement, :published, target_audience: { 'roles' => ['admin'] })
        get :index
        ids = JSON.parse(response.body)['announcements'].pluck('id')
        expect(ids).to contain_exactly(active.id, everyone.id, viewers.id, seeded.id)
      end

      it 'ignores the status filter' do
        get :index, params: { status: 'draft' }
        body = JSON.parse(response.body)
        expect(body['announcements'].pluck('id')).to eq([active.id])
        expect(body['total']).to eq(1)
      end
    end

    describe 'GET #show' do
      it 'returns an active announcement' do
        get :show, params: { id: active.id }
        expect(response).to have_http_status(:ok)
      end

      it 'returns 404 for an active admin-only announcement' do
        admins_only = create(:announcement, :published, target_audience: { 'role' => 'admins' })
        get :show, params: { id: admins_only.id }
        expect(response).to have_http_status(:not_found)
      end

      it 'returns 404 for draft, archived, expired and scheduled announcements' do
        [draft, archived, expired, scheduled].each do |announcement|
          get :show, params: { id: announcement.id }
          expect(response).to have_http_status(:not_found)
        end
      end
    end
  end

  describe 'POST #create' do
    let(:valid_params) do
      { announcement: { title: 'System Update', body: 'Scheduled maintenance', severity: 'info' } }
    end

    it 'creates a new announcement' do
      expect do
        post :create, params: valid_params
      end.to change(Announcement, :count).by(1)
      expect(response).to have_http_status(:created)
    end

    it 'returns errors for invalid params' do
      post :create, params: { announcement: { title: '' } }
      expect(response).to have_http_status(:unprocessable_entity)
    end
  end

  describe 'PUT #update' do
    let(:announcement) { create(:announcement) }

    it 'updates the announcement' do
      put :update, params: { id: announcement.id, announcement: { status: 'published' } }
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['status']).to eq('published')
    end
  end

  describe 'DELETE #destroy' do
    let!(:announcement) { create(:announcement) }

    it 'deletes the announcement' do
      expect do
        delete :destroy, params: { id: announcement.id }
      end.to change(Announcement, :count).by(-1)
      expect(response).to have_http_status(:no_content)
    end
  end
end
