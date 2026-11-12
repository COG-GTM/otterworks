require 'rails_helper'

RSpec.describe Api::V1::Admin::IncidentsController do
  before { set_jwt_env(request) }

  let!(:incident) do
    Incident.create!(
      title: 'file-service upload failures',
      description: 'S3 PutObject returning 500',
      severity: 'high',
      status: 'resolved',
      affected_service: 'file-service',
      devin_session_url: 'https://app.devin.ai/sessions/abc123'
    )
  end

  describe 'GET #index' do
    it 'lists incidents for admins' do
      get :index
      expect(response).to have_http_status(:ok)
      expect(response.parsed_body['incidents'].map { |i| i['id'] }).to include(incident.id)
    end

    it 'forbids listing incidents for non-admin roles' do
      set_jwt_env(request, role: 'user')
      get :index
      expect(response).to have_http_status(:forbidden)
      expect(response.body).not_to include('devin.ai')
    end
  end

  describe 'GET #show' do
    it 'returns the incident for admins' do
      get :show, params: { id: incident.id }
      expect(response).to have_http_status(:ok)
      expect(response.parsed_body['id']).to eq(incident.id)
    end

    it 'forbids reading an incident for non-admin roles' do
      set_jwt_env(request, role: 'editor')
      get :show, params: { id: incident.id }
      expect(response).to have_http_status(:forbidden)
      expect(response.body).not_to include('devin.ai')
    end

    it 'does not call the Devin API for non-admin roles' do
      active = Incident.create!(
        title: 'collab-service websocket drops',
        description: 'Clients disconnected every 30s',
        severity: 'medium',
        status: 'investigating',
        affected_service: 'collab-service',
        devin_session_id: 'devin-session-123'
      )
      expect(DevinSessionService).not_to receive(:get_session)

      set_jwt_env(request, role: 'user')
      get :show, params: { id: active.id }
      expect(response).to have_http_status(:forbidden)
    end
  end
end
