require 'rails_helper'

RSpec.describe Api::V1::Admin::IncidentsController do
  let(:user_id) { SecureRandom.uuid }

  before do
    set_jwt_env(request, user_id: user_id)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(DevinSessionService).to receive(:get_session).and_return(nil)
  end

  describe 'GET #index' do
    let!(:open_incident) { create(:incident, status: 'open', severity: 'low', created_at: 2.hours.ago) }
    let!(:critical) { create(:incident, :investigating, :critical, created_at: 1.hour.ago) }
    let!(:closed) { create(:incident, :closed, created_at: 3.hours.ago) }

    def body_ids
      JSON.parse(response.body)['incidents'].map { |i| i['id'] }
    end

    it 'returns every incident newest first with pagination metadata' do
      get :index

      expect(response).to have_http_status(:ok)
      expect(body_ids).to eq([critical.id, open_incident.id, closed.id])
      expect(JSON.parse(response.body)).to include('total' => 3, 'page' => 1, 'per_page' => 20)
    end

    it 'filters by status' do
      get :index, params: { status: 'open' }

      expect(body_ids).to eq([open_incident.id])
    end

    it 'filters by severity' do
      get :index, params: { severity: 'critical' }

      expect(body_ids).to eq([critical.id])
    end

    it 'filters to active incidents only' do
      get :index, params: { active: 'true' }

      expect(body_ids).to contain_exactly(critical.id, open_incident.id)
    end

    it 'paginates' do
      get :index, params: { page: 2, per_page: 2 }

      expect(body_ids).to eq([closed.id])
      expect(JSON.parse(response.body)).to include('page' => 2, 'per_page' => 2, 'total' => 3)
    end
  end

  describe 'GET #show' do
    it 'serializes the incident' do
      incident = create(:incident)

      get :show, params: { id: incident.id }

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body).to include('id' => incident.id, 'title' => incident.title, 'active' => true)
    end

    it 'refreshes the Devin session status for an active incident' do
      incident = create(:incident, :investigating, :with_devin_session, devin_session_status: 'running')
      allow(DevinSessionService).to receive(:get_session)
        .with(session_id: incident.devin_session_id)
        .and_return({ status: 'finished', url: 'https://app.devin.ai/sessions/new-url' })

      get :show, params: { id: incident.id }

      expect(incident.reload.devin_session_status).to eq('finished')
      expect(incident.devin_session_url).to eq('https://app.devin.ai/sessions/new-url')
    end

    it 'keeps the existing url when the refresh omits one' do
      incident = create(:incident, :investigating, :with_devin_session)
      original_url = incident.devin_session_url
      allow(DevinSessionService).to receive(:get_session).and_return({ status: 'blocked', url: nil })

      get :show, params: { id: incident.id }

      expect(incident.reload.devin_session_url).to eq(original_url)
    end

    it 'leaves the incident untouched when the refresh fails' do
      incident = create(:incident, :investigating, :with_devin_session)

      get :show, params: { id: incident.id }

      expect(incident.reload.devin_session_status).to eq('running')
    end

    it 'does not refresh a resolved incident' do
      incident = create(:incident, :resolved, :with_devin_session)

      get :show, params: { id: incident.id }

      expect(DevinSessionService).not_to have_received(:get_session)
      expect(JSON.parse(response.body)['active']).to be(false)
    end

    it 'returns 404 for an unknown incident' do
      get :show, params: { id: SecureRandom.uuid }

      expect(response).to have_http_status(:not_found)
    end
  end

  describe 'POST #create' do
    let(:valid_params) do
      { incident: { title: 'Search is down', description: 'Suggest endpoint 500s',
                    severity: 'critical', affected_service: 'search-service' } }
    end

    it 'creates an investigating incident owned by the caller' do
      expect { post :create, params: valid_params }.to change(Incident, :count).by(1)

      expect(response).to have_http_status(:created)
      incident = Incident.last
      expect(incident).to have_attributes(status: 'investigating', reporter_id: user_id,
                                          affected_service: 'search-service')
    end

    it 'stores the Devin session details when one is created' do
      allow(DevinSessionService).to receive(:create_session)
        .and_return({ session_id: 'devin-9', url: 'https://app.devin.ai/sessions/devin-9' })

      post :create, params: valid_params

      expect(Incident.last).to have_attributes(devin_session_id: 'devin-9', devin_session_status: 'running',
                                               devin_session_url: 'https://app.devin.ai/sessions/devin-9')
    end

    it 'writes an audit log entry' do
      expect { post :create, params: valid_params }.to change(AuditLog, :count).by(1)

      log = AuditLog.last
      expect(log.action).to eq('incident.created')
      expect(log.changes_made['devin_session_created']).to be(false)
    end

    it 'returns 422 with the validation details' do
      post :create, params: { incident: { title: '', description: '', severity: 'nope' } }

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['error']).to eq('Validation failed')
      expect(body['details']).to include("Title can't be blank")
    end

    it 'returns 400 when the incident payload is missing' do
      post :create, params: { title: 'orphan' }

      expect(response).to have_http_status(:bad_request)
    end
  end

  describe 'PATCH #update' do
    it 'resolves an incident and stamps resolved_at' do
      incident = create(:incident, :investigating)

      patch :update, params: { id: incident.id, incident: { status: 'resolved' } }

      expect(response).to have_http_status(:ok)
      expect(incident.reload).to have_attributes(status: 'resolved')
      expect(incident.resolved_at).to be_present
    end

    it 'closes a resolved incident' do
      incident = create(:incident, :resolved)

      patch :update, params: { id: incident.id, incident: { status: 'closed' } }

      expect(incident.reload.status).to eq('closed')
      expect(incident.closed_at).to be_present
    end

    it 'moves an open incident to investigating and audits the change' do
      incident = create(:incident, status: 'open')

      patch :update, params: { id: incident.id, incident: { status: 'investigating' } }

      expect(incident.reload.status).to eq('investigating')
      log = AuditLog.last
      expect(log.action).to eq('incident.investigating')
      expect(log.changes_made).to include('previous_status' => 'open', 'new_status' => 'investigating')
    end

    it 'rejects an illegal transition' do
      incident = create(:incident, :closed)

      patch :update, params: { id: incident.id, incident: { status: 'investigating' } }

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['error']).to eq('Invalid status transition')
      expect(body['details']).to match(/Cannot transition from 'closed' to 'investigating'/)
    end

    it 'rescues a transition that the model rejects mid-flight' do
      incident = create(:incident, :investigating)
      allow(Incident).to receive(:find).with(incident.id).and_return(incident)
      allow(incident).to receive(:resolve!).and_raise(Incident::InvalidTransitionError, 'raced')

      patch :update, params: { id: incident.id, incident: { status: 'resolved' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['details']).to eq('raced')
    end
  end

  describe 'DELETE #destroy' do
    it 'deletes the incident and audits it' do
      incident = create(:incident)

      expect { delete :destroy, params: { id: incident.id } }.to change(Incident, :count).by(-1)

      expect(response).to have_http_status(:no_content)
      expect(AuditLog.last.action).to eq('incident.deleted')
    end

    it 'refuses to delete an incident with a running Devin session' do
      incident = create(:incident, :with_devin_session)

      expect { delete :destroy, params: { id: incident.id } }.not_to change(Incident, :count)

      expect(response).to have_http_status(:conflict)
      expect(JSON.parse(response.body)['details']).to include(incident.devin_session_id)
    end
  end

  describe 'POST #trigger_session' do
    it 'creates and stores a new Devin session' do
      incident = create(:incident)
      allow(DevinSessionService).to receive(:create_session)
        .and_return({ session_id: 'devin-7', url: 'https://app.devin.ai/sessions/devin-7' })

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:ok)
      expect(incident.reload).to have_attributes(devin_session_id: 'devin-7', devin_session_status: 'running')
    end

    it 'refuses when a session already exists' do
      incident = create(:incident, :with_devin_session)

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(JSON.parse(response.body)['error']).to eq('Incident already has a Devin session')
    end

    it 'returns 503 when the Devin API is unavailable' do
      incident = create(:incident)

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:service_unavailable)
      expect(JSON.parse(response.body)['error']).to eq('Failed to create Devin session')
    end
  end
end
