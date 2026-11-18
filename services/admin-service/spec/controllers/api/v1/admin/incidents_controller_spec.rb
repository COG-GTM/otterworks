require 'rails_helper'

RSpec.describe Api::V1::Admin::IncidentsController do
  let(:user_id) { SecureRandom.uuid }

  before do
    set_jwt_env(request, user_id: user_id, email: 'oncall@otterworks.com')
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(DevinSessionService).to receive(:get_session).and_return(nil)
    allow(SlackNotifierService).to receive(:notify_incident)
  end

  def json
    JSON.parse(response.body)
  end

  shared_examples 'admin only' do
    it 'rejects non-admin users' do
      set_jwt_env(request, role: 'viewer')
      perform
      expect(response).to have_http_status(:forbidden)
      expect(json['error']).to eq('Admin role required')
    end
  end

  describe 'GET #index' do
    let!(:open_low) { create(:incident, severity: 'low', created_at: 3.hours.ago) }
    let!(:investigating_critical) { create(:incident, :investigating, severity: 'critical', created_at: 2.hours.ago) }
    let!(:resolved) { create(:incident, :resolved, created_at: 1.hour.ago) }

    it 'returns incidents newest first with pagination metadata' do
      get :index
      expect(response).to have_http_status(:ok)
      expect(json['incidents'].map { |i| i['id'] }).to eq([resolved.id, investigating_critical.id, open_low.id])
      expect(json).to include('total' => 3, 'page' => 1, 'per_page' => 20)
      expect(response.headers['X-Total-Count']).to eq('3')
    end

    it 'filters by status' do
      get :index, params: { status: 'resolved' }
      expect(json['incidents'].map { |i| i['id'] }).to eq([resolved.id])
    end

    it 'filters by severity' do
      get :index, params: { severity: 'critical' }
      expect(json['incidents'].map { |i| i['id'] }).to eq([investigating_critical.id])
    end

    it 'filters to active incidents' do
      get :index, params: { active: 'true' }
      expect(json['incidents'].map { |i| i['id'] }).to contain_exactly(open_low.id, investigating_critical.id)
    end

    it 'paginates' do
      get :index, params: { page: 2, per_page: 2 }
      expect(json['incidents'].map { |i| i['id'] }).to eq([open_low.id])
      expect(json).to include('page' => 2, 'per_page' => 2)
    end
  end

  describe 'GET #show' do
    it 'returns the incident without polling Devin when there is no session' do
      incident = create(:incident)
      get :show, params: { id: incident.id }
      expect(response).to have_http_status(:ok)
      expect(json['id']).to eq(incident.id)
      expect(DevinSessionService).not_to have_received(:get_session)
    end

    it 'refreshes the Devin session status for an active incident' do
      incident = create(:incident, :investigating, :with_session)
      allow(DevinSessionService).to receive(:get_session)
        .with(session_id: incident.devin_session_id)
        .and_return({ status: 'blocked', url: 'https://app.devin.ai/sessions/new-url' })

      get :show, params: { id: incident.id }

      expect(json['devin_session_status']).to eq('blocked')
      expect(json['devin_session_url']).to eq('https://app.devin.ai/sessions/new-url')
      expect(incident.reload.devin_session_status).to eq('blocked')
    end

    it 'keeps the existing session url when Devin returns none' do
      incident = create(:incident, :investigating, :with_session)
      original_url = incident.devin_session_url
      allow(DevinSessionService).to receive(:get_session).and_return({ status: 'finished', url: nil })

      get :show, params: { id: incident.id }

      expect(json['devin_session_status']).to eq('finished')
      expect(json['devin_session_url']).to eq(original_url)
    end

    it 'leaves the incident untouched when the Devin lookup fails' do
      incident = create(:incident, :investigating, :with_session)
      get :show, params: { id: incident.id }
      expect(DevinSessionService).to have_received(:get_session)
      expect(json['devin_session_status']).to eq('running')
    end

    it 'does not poll Devin for an inactive incident' do
      incident = create(:incident, :resolved, :with_session)
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
      { incident: { title: 'Uploads failing', description: 'S3 500s', severity: 'critical', affected_service: 'file-service' } }
    end

    it_behaves_like 'admin only' do
      let(:perform) { post :create, params: valid_params }
    end

    it 'creates an investigating incident, starts a Devin session and notifies Slack' do
      allow(DevinSessionService).to receive(:create_session)
        .and_return({ session_id: 'devin-abc', url: 'https://app.devin.ai/sessions/devin-abc' })
      allow(AuditLogger).to receive(:log)

      expect { post :create, params: valid_params }.to change(Incident, :count).by(1)

      expect(response).to have_http_status(:created)
      incident = Incident.last
      expect(incident).to have_attributes(
        status: 'investigating',
        reporter_id: user_id,
        devin_session_id: 'devin-abc',
        devin_session_status: 'running'
      )
      expect(SlackNotifierService).to have_received(:notify_incident).with(
        incident: incident,
        session_url: 'https://app.devin.ai/sessions/devin-abc',
        reporter_email: 'oncall@otterworks.com'
      )
      expect(AuditLogger).to have_received(:log).with(
        hash_including(action: 'incident.created', resource_id: incident.id,
                       changes_made: hash_including(devin_session_created: true))
      )
    end

    it 'still creates the incident and notifies Slack when no Devin session is created' do
      post :create, params: valid_params
      expect(response).to have_http_status(:created)
      incident = Incident.last
      expect(incident.devin_session_id).to be_nil
      expect(SlackNotifierService).to have_received(:notify_incident)
        .with(hash_including(incident: incident, session_url: nil))
    end

    it 'returns 422 with details on validation failure' do
      post :create, params: { incident: { title: '', description: '', severity: 'nope' } }
      expect(response).to have_http_status(:unprocessable_entity)
      expect(json['error']).to eq('Validation failed')
      expect(json['details']).to be_present
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'returns 400 when the incident param is missing' do
      post :create, params: { title: 'x' }
      expect(response).to have_http_status(:bad_request)
    end
  end

  describe 'PATCH #update' do
    it_behaves_like 'admin only' do
      let(:perform) { patch :update, params: { id: create(:incident).id, incident: { status: 'resolved' } } }
    end

    it 'moves an open incident to investigating and audits it' do
      incident = create(:incident)
      allow(AuditLogger).to receive(:log)

      patch :update, params: { id: incident.id, incident: { status: 'investigating' } }

      expect(response).to have_http_status(:ok)
      expect(incident.reload.status).to eq('investigating')
      expect(AuditLogger).to have_received(:log).with(
        hash_including(action: 'incident.investigating',
                       changes_made: { previous_status: 'open', new_status: 'investigating' })
      )
    end

    it 'resolves an investigating incident' do
      incident = create(:incident, :investigating)
      patch :update, params: { id: incident.id, incident: { status: 'resolved' } }
      expect(json['status']).to eq('resolved')
      expect(incident.reload.resolved_at).to be_present
    end

    it 'closes a resolved incident' do
      incident = create(:incident, :resolved)
      patch :update, params: { id: incident.id, incident: { status: 'closed' } }
      expect(json['status']).to eq('closed')
      expect(incident.reload.closed_at).to be_present
    end

    it 'rejects an invalid transition' do
      incident = create(:incident)
      patch :update, params: { id: incident.id, incident: { status: 'closed' } }
      expect(response).to have_http_status(:unprocessable_entity)
      expect(json['details']).to eq("Cannot transition from 'open' to 'closed'")
      expect(incident.reload.status).to eq('open')
    end

    it 'maps a concurrent InvalidTransitionError to 422' do
      incident = create(:incident)
      allow_any_instance_of(Incident).to receive(:resolve!)
        .and_raise(Incident::InvalidTransitionError, 'raced')

      patch :update, params: { id: incident.id, incident: { status: 'resolved' } }

      expect(response).to have_http_status(:unprocessable_entity)
      expect(json).to eq('error' => 'Invalid status transition', 'details' => 'raced')
    end
  end

  describe 'DELETE #destroy' do
    it_behaves_like 'admin only' do
      let(:perform) { delete :destroy, params: { id: create(:incident).id } }
    end

    it 'deletes the incident and audits it' do
      incident = create(:incident)
      allow(AuditLogger).to receive(:log)

      expect { delete :destroy, params: { id: incident.id } }.to change(Incident, :count).by(-1)

      expect(response).to have_http_status(:no_content)
      expect(AuditLogger).to have_received(:log)
        .with(hash_including(action: 'incident.deleted', resource_id: incident.id))
    end

    it 'deletes an incident whose Devin session has finished' do
      incident = create(:incident, :with_session, devin_session_status: 'finished')
      delete :destroy, params: { id: incident.id }
      expect(response).to have_http_status(:no_content)
    end

    it 'refuses to delete an incident with a running Devin session' do
      incident = create(:incident, :with_session)
      expect { delete :destroy, params: { id: incident.id } }.not_to change(Incident, :count)
      expect(response).to have_http_status(:conflict)
      expect(json['details']).to include(incident.devin_session_id)
    end
  end

  describe 'POST #trigger_session' do
    it_behaves_like 'admin only' do
      let(:perform) { post :trigger_session, params: { id: create(:incident).id } }
    end

    it 'starts a Devin session and notifies Slack' do
      incident = create(:incident)
      allow(DevinSessionService).to receive(:create_session)
        .with(incident: incident)
        .and_return({ session_id: 'devin-xyz', url: 'https://app.devin.ai/sessions/devin-xyz' })

      post :trigger_session, params: { id: incident.id }

      expect(response).to have_http_status(:ok)
      expect(json).to include('devin_session_id' => 'devin-xyz', 'devin_session_status' => 'running')
      expect(SlackNotifierService).to have_received(:notify_incident).with(
        incident: incident,
        session_url: 'https://app.devin.ai/sessions/devin-xyz',
        reporter_email: 'oncall@otterworks.com'
      )
    end

    it 'refuses when a session already exists' do
      incident = create(:incident, :with_session)
      post :trigger_session, params: { id: incident.id }
      expect(response).to have_http_status(:unprocessable_entity)
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'returns 503 when Devin session creation fails' do
      incident = create(:incident)
      post :trigger_session, params: { id: incident.id }
      expect(response).to have_http_status(:service_unavailable)
      expect(SlackNotifierService).not_to have_received(:notify_incident)
      expect(incident.reload.devin_session_id).to be_nil
    end
  end
end
