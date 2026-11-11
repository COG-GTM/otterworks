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

    context 'when the caller is not an admin' do
      let!(:active) { create(:announcement, :published) }

      before do
        create(:announcement, :archived)
        create(:announcement, :expired)
        set_jwt_env(request, role: 'user')
      end

      it 'returns only active announcements' do
        get :index
        expect(response).to have_http_status(:ok)
        body = JSON.parse(response.body)
        expect(body['announcements'].pluck('id')).to eq([active.id])
        expect(body['total']).to eq(1)
      end

      it 'ignores the status filter' do
        get :index, params: { status: 'draft' }
        body = JSON.parse(response.body)
        expect(body['announcements'].pluck('id')).to eq([active.id])
      end
    end
  end

  describe 'GET #show' do
    let(:draft) { create(:announcement) }
    let(:published) { create(:announcement, :published) }

    it 'returns a draft announcement to an admin' do
      get :show, params: { id: draft.id }
      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['id']).to eq(draft.id)
    end

    context 'when the caller is not an admin' do
      before { set_jwt_env(request, role: 'user') }

      it 'returns an active announcement' do
        get :show, params: { id: published.id }
        expect(response).to have_http_status(:ok)
        expect(JSON.parse(response.body)['id']).to eq(published.id)
      end

      it 'returns not found for a draft announcement' do
        get :show, params: { id: draft.id }
        expect(response).to have_http_status(:not_found)
      end

      it 'returns not found for an archived announcement' do
        get :show, params: { id: create(:announcement, :archived).id }
        expect(response).to have_http_status(:not_found)
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
