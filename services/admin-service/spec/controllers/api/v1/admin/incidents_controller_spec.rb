require 'rails_helper'

RSpec.describe Api::V1::Admin::IncidentsController do
  let(:actor_id) { SecureRandom.uuid }

  before do
    set_jwt_env(request, user_id: actor_id)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(DevinSessionService).to receive(:get_session).and_return(nil)
  end

  describe 'GET #index' do
    let!(:open_incident) { create(:incident, status: 'open', severity: 'critical') }
    let!(:closed_incident) { create(:incident, :closed, severity: 'low', affected_service: 'file-service') }

    it 'lists every incident newest first with pagination metadata' do
      get :index

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['total']).to eq(2)
      expect(body['page']).to eq(1)
      expect(body['per_page']).to eq(20)
      expect(body['incidents'].map { |i| i['id'] }).to eq([closed_incident.id, open_incident.id])
    end

    it 'filters by status' do
      get :index, params: { status: 'closed' }

      expect(JSON.parse(response.body)['incidents'].map { |i| i['id'] }).to eq([closed_incident.id])
    end

    it 'filters by severity' do
      get :index, params: { severity: 'critical' }

      expect(JSON.parse(response.body)['incidents'].map { |i| i['id'] }).to eq([open_incident.id])
    end

    it 'filters to active incidents only' do
      get :index, params: { active: 'true' }

      expect(JSON.parse(response.body)['incidents'].map { |i| i['id'] }).to eq([open_incident.id])
    end

    it 'honours page and per_page' do
      get :index, params: { page: 2, per_page: 1 }

      body = JSON.parse(response.body)
      expect(body['incidents'].map { |i| i['id'] }).to eq([open_incident.id])
      expect(response.headers['X-Total-Count']).to eq('2')
      expect(response.headers['X-Page']).to eq('2')
      expect(response.headers['X-Per-Page']).to eq('1')
    end
  end

  describe 'GET #show' do
    it 'serializes the incident' do
      incident = create(:incident, status: 'open')

      get :show, params: { id: incident.id }

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body).to include('id' => incident.id, 'title' => incident.title, 'active' => true)
    end

    it 'refreshes the Devin session status for an active incident' do
      incident = create(:incident, :investigating, :with_devin_session, devin_session_status: 'running')
      allow(DevinSessionService).to receive(:get_session)
        .with(session_id: incident.devin_session_id)
        .and_return(status: 'finished', url: 'https://app.devin.ai/sessions/new')

      get :show, params: { id: incident.id }

      expect(incident.reload.devin_session_status).to eq('finished')
      expect(incident.devin_session_url).to eq('https://app.devin.ai/sessions/new')
    end

    it 'keeps the existing url when the API omits one' do
      incident = create(:incident, :investigating, :with_devin_session)
      original_url = incident.devin_session_url
      allow(DevinSessionService).to receive(:get_session).and_return(status: 'blocked', url: nil)

      get :show, params: { id: incident.id }

      expect(incident.reload.devin_session_url).to eq(original_url)
      expect(incident.devin_session_status).to eq('blocked')
    end

    it 'leaves the session untouched when the API returns nothing' do
      incident = create(:incident, :investigating, :with_devin_session)

      get :show, params: { id: incident.id }

      expect(incident.reload.devin_session_status).to eq('running')
    end

    it 'does not poll Devin for a resolved incident' do
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
      { incident: { title: 'Search is down', description: '500s on suggest', severity: 'high',
                    affected_service: 'search-service' } }
    end

    it 'creates an investigating incident owned by the caller' do
      expect { post :create, params: valid_params }.to change(Incident, :count).by(1)

      expect(response).to have_http_status(:created)
      incident = Incident.last
      expect(incident).to have_attributes(status: 'investigating', reporter_id: actor_id, severity: 'high')
      expect(JSON.parse(response.body)['id']).to eq(incident.id)
    end

    it 'stores the Devin session details when one is created' do
      allow(DevinSessionService).to receive(:create_session)
        .and_return(session_id: 'devin-9', url: 'https://app.devin.ai/sessions/9')

      post :create, params: valid_params

      expect(Incident.last).to have_attributes(
        devin_session_id: 'devin-9',
        devin_session_url: 'https://app.devin.ai/sessions/9',
        devin_session_status: 'running'
      )
    end

    it 'writes an audit log entry' do
      expect { post :create, params: valid_params }.to change(AuditLog, :count).by(1)

      expect(AuditLog.last).to have_attributes(action: 'incident.created', resource_type: 'Incident')
      expect(AuditLog.last.changes_made['devin_session_created']).to be(false)
    end

    it 'rejects invalid attributes' do
      post :create, params: { incident: { title: '', description: '', severity: 'nope' } }

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['error']).to eq('Validation failed')
      expect(body['details']).to include("Title can't be blank")
    end

    it 'returns 400 when the incident payload is missing' do
      post :create, params: {}

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Missing parameter: incident')
    end
  end

  describe 'PATCH #update' do
    it 'resolves an investigating incident' do
      incident = create(:incident, :investigating)

      patch :update, params: { id: incident.id, incident: { status: 'resolved' } }

      expect(response).to have_http_status(:ok)
      expect(incident.reload.status).to eq('resolved')
      expect(incident.resolved_at).to be_present
      expect(AuditLog.last).to have_attributes(action: 'incident.resolved')
    end

    it 'closes a resolved incident' do
      incident = create(:incident, :resolved)

      patch :update, params: { id: incident.id, incident: { status: 'closed' } }

      expect(incident.reload.status).to eq('closed')
      expect(incident.closed_at).to be_present
    end

    it 'moves an open incident to investigating' do
      incident = create(:incident, status: 'open')

      patch :update, params: { id: incident.id, incident: { status: 'investigating' } }

      expect(incident.reload.status).to eq('investigating')
      expect(AuditLog.last.changes_made).to include('previous_status' => 'open', 'new_status' => 'investigating')
    end

    it 'rejects an invalid transition' do
      incident = create(:incident, :closed)

      patch :update, params: { id: incident.id, incident: { status: 'open' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to eq("Cannot transition from 'closed' to 'open'")
      expect(incident.reload.status).to eq('closed')
    end

    it 'renders a 422 when the model rejects the transition after the guard passes' do
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
    it 'deletes an incident and audits it' do
      incident = create(:incident)

      expect { delete :destroy, params: { id: incident.id } }.to change(Incident, :count).by(-1)

      expect(response).to have_http_status(:no_content)
      expect(AuditLog.last).to have_attributes(action: 'incident.deleted', resource_id: incident.id)
    end

    it 'refuses to delete an incident with a running Devin session' do
      incident = create(:incident, :with_devin_session)

      expect { delete :destroy, params: { id: incident.id } }.not_to change(Incident, :count)

      expect(response).to have_http_status(:conflict)
      expect(JSON.parse(response.body)['details']).to include(incident.devin_session_id)
    end
  end

  describe 'POST #trigger_session' do
    it 'creates and stores a Devin session' do
      incident = create(:incident, :investigating)
      allow(DevinSessionService).to receive(:create_session)
        .with(incident: instance_of(Incident))
        .and_return(session_id: 'devin-42', url: 'https://app.devin.ai/sessions/42')

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:ok)
      expect(incident.reload).to have_attributes(devin_session_id: 'devin-42', devin_session_status: 'running')
    end

    it 'refuses when a session already exists' do
      incident = create(:incident, :with_devin_session)

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['error']).to eq('Incident already has a Devin session')
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'returns 503 when Devin cannot be reached' do
      incident = create(:incident)

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:service_unavailable)
      expect(JSON.parse(response.body)['error']).to eq('Failed to create Devin session')
    end
  end
end
