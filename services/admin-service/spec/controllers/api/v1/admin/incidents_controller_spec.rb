require 'rails_helper'

RSpec.describe Api::V1::Admin::IncidentsController do
  before do
    set_jwt_env(request)
    allow(DevinSessionService).to receive(:get_session)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
  end

  let!(:incident) do
    Incident.create!(
      title: 'File upload failed: secret-plan.pdf',
      description: 'Upload of "secret-plan.pdf" failed in file-service: NoSuchBucket otterworks-files',
      severity: 'critical',
      status: 'investigating',
      affected_service: 'file-service',
      devin_session_id: 'devin-abc123',
      devin_session_url: 'https://app.devin.ai/sessions/abc123',
      devin_session_status: 'running',
      reporter_id: SecureRandom.uuid
    )
  end

  describe 'non-admin access' do
    %w[user viewer editor].each do |role|
      context "with role #{role}" do
        before { set_jwt_env(request, role: role) }

        it 'forbids listing incidents' do
          get :index
          expect(response).to have_http_status(:forbidden)
          expect(response.body).not_to include('secret-plan.pdf')
        end

        it 'forbids reading an incident without contacting Devin or writing the row' do
          expect { get :show, params: { id: incident.id } }.not_to(change { incident.reload.updated_at })
          expect(response).to have_http_status(:forbidden)
          expect(response.body).not_to include('secret-plan.pdf')
          expect(DevinSessionService).not_to have_received(:get_session)
        end

        it 'forbids refreshing the Devin session' do
          post :refresh_session, params: { id: incident.id }
          expect(response).to have_http_status(:forbidden)
          expect(DevinSessionService).not_to have_received(:get_session)
        end

        it 'forbids creating incidents' do
          post :create, params: { incident: { title: 't', description: 'd', severity: 'low' } }
          expect(response).to have_http_status(:forbidden)
        end
      end
    end

    it 'forbids requests without a role' do
      set_jwt_env(request, role: nil)
      get :index
      expect(response).to have_http_status(:forbidden)
    end
  end

  describe 'GET #index' do
    %w[admin super_admin owner].each do |role|
      it "lists incidents for #{role}" do
        set_jwt_env(request, role: role)
        get :index
        expect(response).to have_http_status(:ok)
        body = JSON.parse(response.body)
        expect(body['incidents'].map { |i| i['id'] }).to eq([incident.id])
        expect(body['total']).to eq(1)
      end
    end
  end

  describe 'GET #show' do
    it 'returns the incident without calling the Devin API or updating it' do
      expect { get :show, params: { id: incident.id } }.not_to(change { incident.reload.updated_at })
      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['id']).to eq(incident.id)
      expect(body['devin_session_status']).to eq('running')
      expect(DevinSessionService).not_to have_received(:get_session)
    end
  end

  describe 'POST #refresh_session' do
    it 'refreshes the Devin session status for admins' do
      allow(DevinSessionService).to receive(:get_session)
        .with(session_id: 'devin-abc123')
        .and_return(status: 'finished', url: 'https://app.devin.ai/sessions/abc123-new')

      post :refresh_session, params: { id: incident.id }

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['devin_session_status']).to eq('finished')
      expect(body['devin_session_url']).to eq('https://app.devin.ai/sessions/abc123-new')
      expect(incident.reload.devin_session_status).to eq('finished')
    end

    it 'does not call the Devin API for resolved incidents' do
      incident.resolve!
      post :refresh_session, params: { id: incident.id }
      expect(response).to have_http_status(:ok)
      expect(DevinSessionService).not_to have_received(:get_session)
    end
  end
end
