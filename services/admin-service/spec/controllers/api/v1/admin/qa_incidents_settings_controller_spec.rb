require 'rails_helper'

# QA admin-audit unit layer: incident triage, settings and feature-flag
# authz. Devin and Slack are always stubbed; no real calls are made.
RSpec.describe Api::V1::Admin::IncidentsController, type: :controller do
  let(:actor_id) { SecureRandom.uuid }

  before do
    set_jwt_env(request, user_id: actor_id, role: 'admin')
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(DevinSessionService).to receive(:get_session).and_return(nil)
    allow(SlackNotifierService).to receive(:notify_incident).and_return(nil)
  end

  let(:valid_params) { { incident: { title: 'QA outage', description: 'uploads failing', severity: 'high' } } }

  it 'creates an incident as investigating, stamps reporter and audits incident.created' do
    post :create, params: valid_params
    expect(response).to have_http_status(:created)
    incident = Incident.last
    expect(incident.status).to eq('investigating')
    expect(incident.reporter_id).to eq(actor_id)
    expect(AuditLog.where(action: 'incident.created', resource_id: incident.id, actor_id: actor_id)).to exist
    expect(DevinSessionService).to have_received(:create_session).once
  end

  it 'rejects an invalid severity with 422 and never calls Devin' do
    post :create, params: { incident: valid_params[:incident].merge(severity: 'apocalyptic') }
    expect(response).to have_http_status(:unprocessable_entity)
    expect(DevinSessionService).not_to have_received(:create_session)
  end

  it 'forbids a viewer from creating incidents (no Devin session triggered)' do
    set_jwt_env(request, role: 'viewer')
    post :create, params: valid_params
    expect(response).to have_http_status(:forbidden)
    expect(DevinSessionService).not_to have_received(:create_session)
    expect(SlackNotifierService).not_to have_received(:notify_incident)
  end

  it 'forbids a viewer from triggering a Devin session' do
    incident = Incident.create!(title: 't', description: 'd', severity: 'low', status: 'open')
    set_jwt_env(request, role: 'viewer')
    post :trigger_session, params: { id: incident.id }
    expect(response).to have_http_status(:forbidden)
    expect(DevinSessionService).not_to have_received(:create_session)
  end

  it 'rejects an invalid status transition (closed -> investigating)' do
    incident = Incident.create!(title: 't', description: 'd', severity: 'low', status: 'closed')
    put :update, params: { id: incident.id, incident: { status: 'investigating' }, status: 'investigating' }
    expect(response).to have_http_status(:unprocessable_entity)
    expect(incident.reload.status).to eq('closed')
  end

  it 'refuses to delete an incident with a running Devin session' do
    incident = Incident.create!(title: 't', description: 'd', severity: 'low', status: 'investigating',
                                devin_session_id: 'devin-x', devin_session_status: 'running')
    delete :destroy, params: { id: incident.id }
    expect(response).to have_http_status(:conflict)
    expect(Incident.exists?(incident.id)).to be true
  end

  it 'returns 404 for an unknown incident' do
    get :show, params: { id: SecureRandom.uuid }
    expect(response).to have_http_status(:not_found)
  end
end

RSpec.describe Api::V1::Admin::SettingsController, type: :controller do
  before { set_jwt_env(request, role: 'admin') }

  it 'forbids a viewer from changing Slack settings' do
    set_jwt_env(request, role: 'viewer')
    put :update_slack_notifications, params: { enabled: true }
    expect(response).to have_http_status(:forbidden)
  end

  it 'forbids a viewer from setting Devin credentials' do
    set_jwt_env(request, role: 'viewer')
    put :update_devin_credentials, params: { api_key: 'k', org_id: 'o' }
    expect(response).to have_http_status(:forbidden)
  end

  it 'rejects a non-Slack webhook host (SSRF guard)' do
    put :update_slack_notifications, params: { webhook_url: 'https://evil.example.com/hook' }
    expect(response).to have_http_status(:bad_request)
  end

  it 'rejects a plain-http Slack webhook' do
    put :update_slack_notifications, params: { webhook_url: 'http://hooks.slack.com/services/T/B/x' }
    expect(response).to have_http_status(:bad_request)
  end

  it 'rejects an empty update' do
    put :update_slack_notifications, params: {}
    expect(response).to have_http_status(:bad_request)
  end

  it 'never echoes Devin credential values' do
    get :devin_credentials
    expect(response).to have_http_status(:ok)
    expect(response.body).not_to match(/apk_|api_key"\s*:\s*"[^"]+"/)
  end
end

RSpec.describe Api::V1::Admin::FeaturesController, type: :controller do
  let(:actor_id) { SecureRandom.uuid }

  before { set_jwt_env(request, user_id: actor_id, role: 'admin') }

  it 'creates a flag and audits feature_flag.created with the actor' do
    post :create, params: { feature: { name: "qa_flag_#{SecureRandom.hex(3)}", enabled: true, rollout_percentage: 50 } }
    expect(response).to have_http_status(:created)
    expect(AuditLog.where(action: 'feature_flag.created', actor_id: actor_id)).to exist
  end

  it 'forbids an editor from creating flags' do
    set_jwt_env(request, role: 'editor')
    post :create, params: { feature: { name: 'nope', enabled: true } }
    expect(response).to have_http_status(:forbidden)
  end

  it 'rejects a rollout percentage above 100' do
    post :create, params: { feature: { name: 'qa_bad_rollout', enabled: true, rollout_percentage: 150 } }
    expect(response).to have_http_status(:unprocessable_entity)
  end
end
