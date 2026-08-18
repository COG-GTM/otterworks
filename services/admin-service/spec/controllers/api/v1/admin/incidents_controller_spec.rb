require 'rails_helper'

RSpec.describe Api::V1::Admin::IncidentsController do
  let(:user_id) { SecureRandom.uuid }

  before do
    set_jwt_env(request, user_id: user_id)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(DevinSessionService).to receive(:get_session).and_return(nil)
  end

  describe 'GET #index' do
    let!(:critical) { create(:incident, severity: 'critical', status: 'open', created_at: 2.hours.ago) }
    let!(:resolved) { create(:incident, :resolved, severity: 'low', created_at: 1.hour.ago) }

    it 'lists incidents newest first with pagination metadata' do
      get :index

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['total']).to eq(2)
      expect(body['page']).to eq(1)
      expect(body['per_page']).to eq(20)
      expect(body['incidents'].map { |i| i['id'] }).to eq([resolved.id, critical.id])
    end

    it 'filters by status' do
      get :index, params: { status: 'resolved' }

      expect(JSON.parse(response.body)['incidents'].map { |i| i['id'] }).to eq([resolved.id])
    end

    it 'filters by severity' do
      get :index, params: { severity: 'critical' }

      expect(JSON.parse(response.body)['incidents'].map { |i| i['id'] }).to eq([critical.id])
    end

    it 'filters to active incidents only' do
      get :index, params: { active: 'true' }

      expect(JSON.parse(response.body)['incidents'].map { |i| i['id'] }).to eq([critical.id])
    end

    it 'honours page and per_page' do
      get :index, params: { page: 2, per_page: 1 }

      body = JSON.parse(response.body)
      expect(body['per_page']).to eq(1)
      expect(body['incidents'].map { |i| i['id'] }).to eq([critical.id])
    end
  end

  describe 'GET #show' do
    it 'renders the incident' do
      incident = create(:incident)

      get :show, params: { id: incident.id }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)).to include('id' => incident.id, 'title' => incident.title, 'active' => true)
    end

    it 'refreshes the Devin session status for an active incident' do
      incident = create(:incident, :investigating, :with_devin_session)
      allow(DevinSessionService).to receive(:get_session)
        .and_return(status: 'finished', url: 'https://app.devin.ai/sessions/new')

      get :show, params: { id: incident.id }

      expect(incident.reload.devin_session_status).to eq('finished')
      expect(incident.devin_session_url).to eq('https://app.devin.ai/sessions/new')
      expect(DevinSessionService).to have_received(:get_session).with(session_id: incident.devin_session_id)
    end

    it 'keeps the stored url when the refresh omits one' do
      incident = create(:incident, :investigating, :with_devin_session)
      allow(DevinSessionService).to receive(:get_session).and_return(status: 'blocked', url: nil)

      get :show, params: { id: incident.id }

      expect(incident.reload.devin_session_url).to eq('https://app.devin.ai/sessions/abc')
    end

    it 'does not refresh a resolved incident' do
      incident = create(:incident, :resolved, :with_devin_session)

      get :show, params: { id: incident.id }

      expect(DevinSessionService).not_to have_received(:get_session)
    end

    it 'returns 404 for an unknown incident' do
      get :show, params: { id: SecureRandom.uuid }

      expect(response).to have_http_status(:not_found)
    end
  end

  describe 'POST #create' do
    let(:valid_params) do
      { incident: { title: 'Uploads failing', description: 'S3 puts return 500', severity: 'critical',
                    affected_service: 'file-service' } }
    end

    it 'creates an investigating incident owned by the caller and audits it' do
      expect { post :create, params: valid_params }.to change(Incident, :count).by(1)

      expect(response).to have_http_status(:created)
      incident = Incident.last
      expect(incident.status).to eq('investigating')
      expect(incident.reporter_id).to eq(user_id)
      expect(AuditLog.last.action).to eq('incident.created')
    end

    it 'stores the Devin session details when one is created' do
      allow(DevinSessionService).to receive(:create_session)
        .and_return(session_id: 'devin-9', url: 'https://app.devin.ai/sessions/devin-9')

      post :create, params: valid_params

      incident = Incident.last
      expect(incident.devin_session_id).to eq('devin-9')
      expect(incident.devin_session_url).to eq('https://app.devin.ai/sessions/devin-9')
      expect(incident.devin_session_status).to eq('running')
      expect(JSON.parse(response.body)['devin_session_id']).to eq('devin-9')
    end

    it 'returns 422 with validation details when the payload is invalid' do
      post :create, params: { incident: { title: '', description: '', severity: 'nope' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to be_present
      expect(Incident.count).to eq(0)
    end

    it 'returns 400 when the incident key is missing' do
      post :create, params: { title: 'orphan' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to match(/Missing parameter: incident/)
    end
  end

  describe 'PATCH #update' do
    it 'resolves an incident and audits the transition' do
      incident = create(:incident, :investigating)

      patch :update, params: { id: incident.id, incident: { status: 'resolved' } }

      expect(response).to have_http_status(:ok)
      expect(incident.reload.status).to eq('resolved')
      expect(incident.resolved_at).to be_present
      expect(AuditLog.last.action).to eq('incident.resolved')
    end

    it 'moves an open incident to investigating' do
      incident = create(:incident, status: 'open')

      patch :update, params: { id: incident.id, incident: { status: 'investigating' } }

      expect(incident.reload.status).to eq('investigating')
    end

    it 'closes a resolved incident' do
      incident = create(:incident, :resolved)

      patch :update, params: { id: incident.id, incident: { status: 'closed' } }

      expect(incident.reload.status).to eq('closed')
      expect(incident.closed_at).to be_present
    end

    it 'rejects an invalid transition with 422' do
      incident = create(:incident, status: 'open')

      patch :update, params: { id: incident.id, incident: { status: 'closed' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to match(/Cannot transition from 'open' to 'closed'/)
      expect(incident.reload.status).to eq('open')
    end

    it 'renders 422 when the model raises InvalidTransitionError late' do
      incident = create(:incident, :investigating)
      allow(Incident).to receive(:find).and_return(incident)
      allow(incident).to receive_messages(can_transition_to?: true)
      allow(incident).to receive(:resolve!).and_raise(Incident::InvalidTransitionError, 'race lost')

      patch :update, params: { id: incident.id, incident: { status: 'resolved' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to eq('race lost')
    end
  end

  describe 'DELETE #destroy' do
    it 'deletes the incident and writes an audit entry' do
      incident = create(:incident)

      expect { delete :destroy, params: { id: incident.id } }.to change(Incident, :count).by(-1)

      expect(response).to have_http_status(:no_content)
      expect(AuditLog.last.action).to eq('incident.deleted')
    end

    it 'refuses to delete an incident with a running Devin session' do
      incident = create(:incident, :with_devin_session)

      delete :destroy, params: { id: incident.id }

      expect(response).to have_http_status(:conflict)
      expect(JSON.parse(response.body)['details']).to match(/before deleting/)
      expect(Incident.exists?(incident.id)).to be(true)
    end
  end

  describe 'POST #trigger_session' do
    it 'creates a session and returns the updated incident' do
      incident = create(:incident)
      allow(DevinSessionService).to receive(:create_session)
        .and_return(session_id: 'devin-42', url: 'https://app.devin.ai/sessions/devin-42')

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:ok)
      expect(incident.reload.devin_session_id).to eq('devin-42')
      expect(incident.devin_session_status).to eq('running')
    end

    it 'rejects an incident that already has a session' do
      incident = create(:incident, :with_devin_session)

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['error']).to match(/already has a Devin session/)
    end

    it 'returns 503 when the Devin API cannot be reached' do
      incident = create(:incident)

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:service_unavailable)
      expect(JSON.parse(response.body)['error']).to eq('Failed to create Devin session')
    end
  end
end
