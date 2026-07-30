require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  let(:firing_alert) do
    {
      status: 'firing',
      labels: { alertname: 'SearchService5xx', severity: 'critical', affected_service: 'search-service' },
      annotations: { summary: 'Search service returning 5xx', description: 'Error rate above 10%' }
    }
  end

  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(false)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(Rails.logger).to receive(:info)
    allow(Rails.logger).to receive(:warn)
    allow(Rails.logger).to receive(:error)
  end

  describe 'POST #ingest' do
    it 'rejects a payload without an alerts array' do
      post :ingest, params: { status: 'firing' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Missing alerts array')
    end

    it 'creates an open incident when auto-investigate is disabled' do
      expect { post :ingest, params: { alerts: [firing_alert] } }.to change(Incident, :count).by(1)

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body).to include('received' => 1, 'processed' => 1)
      expect(body['incidents'].first['devin_session']).to be(false)

      incident = Incident.last
      expect(incident.status).to eq('open')
      expect(incident.severity).to eq('critical')
      expect(incident.affected_service).to eq('search-service')
      expect(incident.title).to eq('Search service returning 5xx')
      expect(incident.reporter_id).to be_nil
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'creates an investigating incident with a Devin session when auto-investigate is on' do
      allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
      allow(DevinSessionService).to receive(:create_session)
        .and_return({ session_id: 'sess-2', url: 'https://app.devin.ai/sessions/2' })

      post :ingest, params: { alerts: [firing_alert] }

      incident = Incident.last
      expect(incident.status).to eq('investigating')
      expect(incident.devin_session_id).to eq('sess-2')
      expect(incident.devin_session_status).to eq('running')
      expect(JSON.parse(response.body)['incidents'].first['devin_session']).to be(true)
    end

    it 'builds a description containing the alert name, runbook and source' do
      alert = firing_alert.deep_merge(annotations: { runbook_url: 'https://runbooks.otterworks.app/search' })

      post :ingest, params: { alerts: [alert] }

      description = Incident.last.description
      expect(description).to include('Error rate above 10%')
      expect(description).to include('**Alert**: SearchService5xx')
      expect(description).to include('**Runbook**: https://runbooks.otterworks.app/search')
      expect(description).to include('**Source**: Grafana Unified Alerting')
    end

    it 'falls back to the service label and a generated title' do
      alert = { status: 'firing', labels: { alertname: 'DocLatency', severity: 'warning',
                                            service: 'document-service' } }

      post :ingest, params: { alerts: [alert] }

      incident = Incident.last
      expect(incident.affected_service).to eq('document-service')
      expect(incident.severity).to eq('medium')
      expect(incident.title).to eq('DocLatency: document-service alert firing')
    end

    it 'omits the alert line when the alert has no name' do
      alert = { status: 'firing', labels: { severity: 'info', affected_service: 'auth-service' },
                annotations: { summary: 'Auth latency' } }

      post :ingest, params: { alerts: [alert] }

      incident = Incident.last
      expect(incident.severity).to eq('low')
      expect(incident.description).not_to include('**Alert**')
      expect(incident.description).to include('**Source**: Grafana Unified Alerting')
    end

    it 'maps unknown severities to medium' do
      alert = firing_alert.deep_merge(labels: { severity: 'not-a-severity' })

      post :ingest, params: { alerts: [alert] }

      expect(Incident.last.severity).to eq('medium')
    end

    it 'deduplicates against an already open incident' do
      existing = create(:incident, :investigating, affected_service: 'search-service')

      expect { post :ingest, params: { alerts: [firing_alert] } }.not_to change(Incident, :count)

      entry = JSON.parse(response.body)['incidents'].first
      expect(entry).to include('skipped' => true, 'incident_id' => existing.id, 'reason' => 'duplicate')
    end

    it 'ignores alerts without an affected service' do
      alert = { status: 'firing', labels: { alertname: 'Orphan', severity: 'high' } }

      expect { post :ingest, params: { alerts: [alert] } }.not_to change(Incident, :count)

      expect(JSON.parse(response.body)).to include('received' => 1, 'processed' => 0)
    end

    it 'ignores alerts in an unknown state' do
      alert = firing_alert.merge(status: 'pending')

      expect { post :ingest, params: { alerts: [alert] } }.not_to change(Incident, :count)

      expect(JSON.parse(response.body)['processed']).to eq(0)
    end

    it 'logs and skips an alert that fails validation' do
      alert = firing_alert.deep_merge(labels: { affected_service: 'not-a-real-service' })

      expect { post :ingest, params: { alerts: [alert] } }.not_to change(Incident, :count)

      expect(JSON.parse(response.body)['processed']).to eq(0)
      expect(Rails.logger).to have_received(:error).with(/Failed to create incident from alert/)
    end
  end

  describe 'resolved alerts' do
    it 'auto-resolves the matching open incident' do
      incident = create(:incident, :investigating, affected_service: 'search-service')

      post :ingest, params: { alerts: [firing_alert.merge(status: 'resolved')] }

      expect(incident.reload.status).to eq('resolved')
      expect(JSON.parse(response.body)['processed']).to eq(0)
    end

    it 'does nothing when no incident is open' do
      post :ingest, params: { alerts: [firing_alert.merge(status: 'resolved')] }

      expect(response).to have_http_status(:ok)
    end

    it 'ignores a resolved alert without an affected service' do
      alert = { status: 'resolved', labels: { alertname: 'Orphan' } }

      post :ingest, params: { alerts: [alert] }

      expect(response).to have_http_status(:ok)
    end

    it 'logs when the incident cannot be transitioned' do
      create(:incident, :investigating, affected_service: 'search-service')
      stub_const('Incident::VALID_TRANSITIONS', { 'investigating' => [] })

      post :ingest, params: { alerts: [firing_alert.merge(status: 'resolved')] }

      expect(Rails.logger).to have_received(:warn).with(/Could not auto-resolve incident/)
    end
  end

  describe 'webhook secret verification' do
    before do
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return('hook-secret')
    end

    it 'rejects a request without the secret' do
      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:unauthorized)
    end

    it 'accepts the X-Alert-Secret header' do
      request.headers['X-Alert-Secret'] = 'hook-secret'

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:ok)
    end

    it 'accepts a bearer token' do
      request.headers['Authorization'] = 'Bearer hook-secret'

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:ok)
    end
  end
end
