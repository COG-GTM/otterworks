require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  def firing_alert(overrides = {})
    {
      status: 'firing',
      labels: { alertname: 'SearchService5xx', severity: 'critical', affected_service: 'search-service' },
      annotations: { summary: 'Search service returning 5xx', description: 'Error rate above 10%' }
    }.deep_merge(overrides)
  end

  before do
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return(nil)
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
  end

  describe 'POST #ingest' do
    it 'rejects a payload without an alerts array' do
      post :ingest, params: { status: 'firing' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Missing alerts array')
    end

    it 'creates an investigating incident from a firing alert' do
      expect { post :ingest, params: { alerts: [firing_alert] } }.to change(Incident, :count).by(1)

      expect(response).to have_http_status(:ok)
      incident = Incident.last
      expect(incident).to have_attributes(
        title: 'Search service returning 5xx',
        severity: 'critical',
        status: 'investigating',
        affected_service: 'search-service',
        reporter_id: nil
      )
      expect(incident.description).to include('Error rate above 10%', '**Alert**: SearchService5xx',
                                              '**Source**: Grafana Unified Alerting')
      body = JSON.parse(response.body)
      expect(body).to include('received' => 1, 'processed' => 1)
      expect(body['incidents'].first).to include('incident_id' => incident.id, 'devin_session' => false)
    end

    it 'attaches the Devin session when one is created' do
      allow(DevinSessionService).to receive(:create_session)
        .and_return(session_id: 'devin-7', url: 'https://app.devin.ai/sessions/7')

      post :ingest, params: { alerts: [firing_alert] }

      expect(Incident.last).to have_attributes(
        devin_session_id: 'devin-7',
        devin_session_url: 'https://app.devin.ai/sessions/7',
        devin_session_status: 'running'
      )
      expect(JSON.parse(response.body)['incidents'].first['devin_session']).to be(true)
    end

    it 'leaves the incident open and skips Devin when auto-investigate is disabled' do
      allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(false)

      post :ingest, params: { alerts: [firing_alert] }

      expect(Incident.last.status).to eq('open')
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'maps grafana severities onto incident severities' do
      post :ingest, params: { alerts: [firing_alert(labels: { severity: 'warning' })] }

      expect(Incident.last.severity).to eq('medium')
    end

    it 'defaults an unrecognised severity to medium' do
      post :ingest, params: { alerts: [firing_alert(labels: { severity: 'page-me' })] }

      expect(Incident.last.severity).to eq('medium')
    end

    it 'falls back to the service label and a synthesised title' do
      alert = { status: 'firing', labels: { alertname: 'FileServiceDown', service: 'file-service' } }

      post :ingest, params: { alerts: [alert] }

      expect(Incident.last).to have_attributes(
        title: 'FileServiceDown: file-service alert firing',
        affected_service: 'file-service'
      )
    end

    it 'includes the runbook link when the alert carries one' do
      alert = firing_alert(annotations: { runbook_url: 'https://runbooks.otterworks.dev/search' })

      post :ingest, params: { alerts: [alert] }

      expect(Incident.last.description).to include('**Runbook**: https://runbooks.otterworks.dev/search')
    end

    it 'omits the alert line from the description when the alert is unnamed' do
      alert = { status: 'firing', labels: { affected_service: 'search-service' },
                annotations: { summary: 'Unnamed alert', description: 'body' } }

      post :ingest, params: { alerts: [alert] }

      expect(Incident.last.description)
        .to eq("body\n\n**Source**: Grafana Unified Alerting (auto-generated incident)")
    end

    it 'skips a firing alert without an affected service' do
      alert = { status: 'firing', labels: { alertname: 'Orphan' }, annotations: { summary: 'no service' } }

      expect { post :ingest, params: { alerts: [alert] } }.not_to change(Incident, :count)

      expect(JSON.parse(response.body)).to include('received' => 1, 'processed' => 0)
    end

    it 'deduplicates against an already-open incident for the service' do
      existing = create(:incident, status: 'open', affected_service: 'search-service')

      expect { post :ingest, params: { alerts: [firing_alert] } }.not_to change(Incident, :count)

      expect(JSON.parse(response.body)['incidents'].first)
        .to include('skipped' => true, 'incident_id' => existing.id, 'reason' => 'duplicate')
    end

    it 'ignores alert statuses other than firing and resolved' do
      expect { post :ingest, params: { alerts: [firing_alert(status: 'pending')] } }.not_to change(Incident, :count)

      expect(JSON.parse(response.body)['processed']).to eq(0)
    end

    it 'logs and skips an alert whose incident fails validation' do
      alert = firing_alert(labels: { affected_service: 'not-a-real-service' })
      allow(Rails.logger).to receive(:error)

      expect { post :ingest, params: { alerts: [alert] } }.not_to change(Incident, :count)

      expect(Rails.logger).to have_received(:error).with(/Failed to create incident from alert SearchService5xx/)
      expect(JSON.parse(response.body)['processed']).to eq(0)
    end

    it 'auto-resolves the open incident on a resolved alert' do
      incident = create(:incident, :investigating, affected_service: 'search-service')

      post :ingest, params: { alerts: [firing_alert(status: 'resolved')] }

      expect(incident.reload.status).to eq('resolved')
      expect(JSON.parse(response.body)['processed']).to eq(0)
    end

    it 'ignores a resolved alert with no matching incident' do
      post :ingest, params: { alerts: [firing_alert(status: 'resolved')] }

      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(0)
    end

    it 'ignores a resolved alert without an affected service' do
      post :ingest, params: { alerts: [{ status: 'resolved', labels: { alertname: 'Orphan' } }] }

      expect(response).to have_http_status(:ok)
    end

    it 'warns when the incident refuses to be auto-resolved' do
      incident = create(:incident, :investigating, affected_service: 'search-service')
      relation = instance_double(ActiveRecord::Relation)
      allow(Incident).to receive(:where).and_return(relation)
      allow(relation).to receive_messages(where: relation, first: incident)
      allow(incident).to receive(:resolve!).and_raise(Incident::InvalidTransitionError, 'already closed')
      allow(Rails.logger).to receive(:warn)

      post :ingest, params: { alerts: [firing_alert(status: 'resolved')] }

      expect(response).to have_http_status(:ok)
      expect(Rails.logger).to have_received(:warn).with(/Could not auto-resolve incident #{incident.id}/)
    end
  end

  describe 'webhook authentication' do
    before { allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return('s3cret') }

    it 'rejects a request without the shared secret' do
      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:unauthorized)
      expect(Incident.count).to eq(0)
    end

    it 'accepts the secret in the X-Alert-Secret header' do
      request.headers['X-Alert-Secret'] = 's3cret'

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(1)
    end

    it 'accepts the secret as a bearer token' do
      request.headers['Authorization'] = 'Bearer s3cret'

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:ok)
    end

    it 'rejects a wrong secret' do
      request.headers['X-Alert-Secret'] = 'nope'

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:unauthorized)
    end
  end
end
