require 'rails_helper'

RSpec.describe Api::V1::Admin::IncidentsController do
  let(:actor_id) { SecureRandom.uuid }

  before do
    set_jwt_env(request, user_id: actor_id)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(DevinSessionService).to receive(:get_session).and_return(nil)
  end

  describe 'GET #index' do
    let!(:open_incident) { create(:incident, status: 'open', severity: 'low', affected_service: 'auth-service') }
    let!(:resolved) { create(:incident, :resolved, severity: 'critical', affected_service: 'file-service') }

    it 'returns paginated incidents' do
      get :index

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body['incidents'].length).to eq(2)
      expect(body['total']).to eq(2)
      expect(body['page']).to eq(1)
      expect(body['per_page']).to eq(20)
    end

    it 'filters by status' do
      get :index, params: { status: 'resolved' }

      expect(JSON.parse(response.body)['incidents'].map { |i| i['id'] }).to eq([resolved.id])
    end

    it 'filters by severity' do
      get :index, params: { severity: 'low' }

      expect(JSON.parse(response.body)['incidents'].map { |i| i['id'] }).to eq([open_incident.id])
    end

    it 'filters to active incidents' do
      get :index, params: { active: 'true' }

      expect(JSON.parse(response.body)['incidents'].map { |i| i['id'] }).to eq([open_incident.id])
    end
  end

  describe 'GET #show' do
    it 'returns the incident' do
      incident = create(:incident)

      get :show, params: { id: incident.id }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['id']).to eq(incident.id)
      expect(DevinSessionService).not_to have_received(:get_session)
    end

    it 'refreshes the Devin session status for an active incident' do
      incident = create(:incident, :investigating, :with_devin_session)
      allow(DevinSessionService).to receive(:get_session)
        .and_return({ status: 'finished', url: 'https://app.devin.ai/sessions/new' })

      get :show, params: { id: incident.id }

      expect(incident.reload.devin_session_status).to eq('finished')
      expect(incident.devin_session_url).to eq('https://app.devin.ai/sessions/new')
    end

    it 'keeps the existing url when the API omits one' do
      incident = create(:incident, :investigating, :with_devin_session)
      allow(DevinSessionService).to receive(:get_session).and_return({ status: 'blocked', url: nil })

      get :show, params: { id: incident.id }

      expect(incident.reload.devin_session_url).to eq('https://app.devin.ai/sessions/abc123')
    end

    it 'leaves the incident untouched when the API returns nothing' do
      incident = create(:incident, :investigating, :with_devin_session)

      get :show, params: { id: incident.id }

      expect(incident.reload.devin_session_status).to eq('running')
    end

    it 'returns 404 for an unknown incident' do
      get :show, params: { id: SecureRandom.uuid }

      expect(response).to have_http_status(:not_found)
    end
  end

  describe 'POST #create' do
    let(:valid_params) do
      { incident: { title: 'Search is down', description: 'Suggest endpoint 500s',
                    severity: 'high', affected_service: 'search-service' } }
    end

    it 'creates an investigating incident owned by the caller' do
      expect { post :create, params: valid_params }.to change(Incident, :count).by(1)

      expect(response).to have_http_status(:created)
      body = JSON.parse(response.body)
      expect(body['status']).to eq('investigating')
      expect(Incident.last.reporter_id).to eq(actor_id)
    end

    it 'stores the Devin session returned by the service' do
      allow(DevinSessionService).to receive(:create_session)
        .and_return({ session_id: 'sess-9', url: 'https://app.devin.ai/sessions/9' })

      post :create, params: valid_params

      incident = Incident.last
      expect(incident.devin_session_id).to eq('sess-9')
      expect(incident.devin_session_url).to eq('https://app.devin.ai/sessions/9')
      expect(incident.devin_session_status).to eq('running')
    end

    it 'writes an audit log entry' do
      expect { post :create, params: valid_params }.to change(AuditLog, :count).by(1)

      expect(AuditLog.last.action).to eq('incident.created')
    end

    it 'returns 422 for an invalid incident' do
      post :create, params: { incident: { title: '', description: '', severity: 'nope' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to be_present
    end

    it 'returns 400 when the incident key is missing' do
      post :create, params: { title: 'orphan' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to match(/incident/)
    end
  end

  describe 'PUT #update' do
    it 'resolves an investigating incident' do
      incident = create(:incident, :investigating)

      put :update, params: { id: incident.id, incident: { status: 'resolved' } }

      expect(response).to have_http_status(:ok)
      expect(incident.reload.status).to eq('resolved')
      expect(incident.resolved_at).to be_present
      expect(AuditLog.last.action).to eq('incident.resolved')
    end

    it 'closes a resolved incident' do
      incident = create(:incident, :resolved)

      put :update, params: { id: incident.id, incident: { status: 'closed' } }

      expect(incident.reload.status).to eq('closed')
      expect(incident.closed_at).to be_present
    end

    it 'moves an open incident to investigating' do
      incident = create(:incident, status: 'open')

      put :update, params: { id: incident.id, incident: { status: 'investigating' } }

      expect(incident.reload.status).to eq('investigating')
    end

    it 'rejects an invalid transition' do
      incident = create(:incident, :closed)

      put :update, params: { id: incident.id, incident: { status: 'open' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to match(/Cannot transition from 'closed'/)
    end

    it 'renders 422 when the model rejects the transition' do
      incident = create(:incident, :investigating)
      allow(Incident).to receive(:find).and_return(incident)
      allow(incident).to receive(:resolve!).and_raise(Incident::InvalidTransitionError, 'model says no')

      put :update, params: { id: incident.id, incident: { status: 'resolved' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to eq('model says no')
    end
  end

  describe 'DELETE #destroy' do
    it 'deletes an incident without an active session' do
      incident = create(:incident, :resolved)

      expect { delete :destroy, params: { id: incident.id } }.to change(Incident, :count).by(-1)

      expect(response).to have_http_status(:no_content)
      expect(AuditLog.last.action).to eq('incident.deleted')
    end

    it 'refuses to delete an incident with a running Devin session' do
      incident = create(:incident, :investigating, :with_devin_session)

      expect { delete :destroy, params: { id: incident.id } }.not_to change(Incident, :count)

      expect(response).to have_http_status(:conflict)
      expect(JSON.parse(response.body)['details']).to match(/Stop Devin session/)
    end
  end

  describe 'POST #trigger_session' do
    it 'creates and stores a new Devin session' do
      incident = create(:incident, :investigating)
      allow(DevinSessionService).to receive(:create_session)
        .and_return({ session_id: 'sess-7', url: 'https://app.devin.ai/sessions/7' })

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:ok)
      expect(incident.reload.devin_session_id).to eq('sess-7')
      expect(incident.devin_session_status).to eq('running')
    end

    it 'rejects an incident that already has a session' do
      incident = create(:incident, :investigating, :with_devin_session)

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['error']).to match(/already has a Devin session/)
    end

    it 'returns 503 when session creation fails' do
      incident = create(:incident, :investigating)

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:service_unavailable)
      expect(JSON.parse(response.body)['error']).to match(/Failed to create Devin session/)
    end
  end
end
