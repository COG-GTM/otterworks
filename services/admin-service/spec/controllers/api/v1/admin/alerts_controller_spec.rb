require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
  end

  def firing_alert(labels: {}, summary: 'File upload failed: a.txt')
    {
      status: 'firing',
      labels: {
        alertname: 'FileUploadFailed',
        severity: 'critical',
        affected_service: 'file-service'
      }.merge(labels),
      annotations: { summary: summary, description: summary }
    }
  end

  describe 'POST #ingest' do
    it 'creates an incident and triggers a Devin session' do
      post :ingest, params: { alerts: [firing_alert] }
      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(1)
      expect(DevinSessionService).to have_received(:create_session).once
    end

    it 'dedupes repeated alerts for the same service by default' do
      post :ingest, params: { alerts: [firing_alert] }
      post :ingest, params: { alerts: [firing_alert] }
      expect(Incident.count).to eq(1)
    end

    it 'creates one incident per alert when dedup=false' do
      3.times do
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      end
      expect(Incident.count).to eq(3)
      expect(DevinSessionService).to have_received(:create_session).exactly(3).times
    end

    it 'creates a new incident with dedup=false even when one is already open' do
      post :ingest, params: { alerts: [firing_alert] }
      post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      expect(Incident.count).to eq(2)
    end

    it 'rejects payloads without an alerts array' do
      post :ingest, params: { foo: 'bar' }
      expect(response).to have_http_status(:bad_request)
    end

    it 'passes the reporter_email label through to the Slack notification' do
      allow(SlackNotifierService).to receive(:notify_incident)

      post :ingest, params: { alerts: [firing_alert(labels: { reporter_email: 'preston@example.com' })] }

      expect(SlackNotifierService).to have_received(:notify_incident)
        .with(hash_including(reporter_email: 'preston@example.com'))
    end

    it 'passes a nil reporter_email when the alert has no reporter label' do
      allow(SlackNotifierService).to receive(:notify_incident)

      post :ingest, params: { alerts: [firing_alert] }

      expect(SlackNotifierService).to have_received(:notify_incident)
        .with(hash_including(reporter_email: nil))
    end
  end
end

RSpec.describe Api::V1::Admin::AlertsController, 'lifecycle and auth' do
  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(SlackNotifierService).to receive(:notify_incident)
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return(nil)
  end

  def alert(status: 'firing', labels: {}, annotations: {})
    {
      status: status,
      labels: { alertname: 'SearchSuggest5xx', severity: 'warning', affected_service: 'search-service' }.merge(labels),
      annotations: { summary: 'Search suggest failing' }.merge(annotations)
    }
  end

  def json
    JSON.parse(response.body)
  end

  it 'stores the Devin session on the incident when one is created' do
    allow(DevinSessionService).to receive(:create_session)
      .and_return({ session_id: 'devin-9', url: 'https://app.devin.ai/sessions/devin-9' })

    post :ingest, params: { alerts: [alert] }

    incident = Incident.last
    expect(incident).to have_attributes(status: 'investigating', severity: 'medium',
                                        devin_session_id: 'devin-9', devin_session_status: 'running')
    expect(json['incidents']).to eq([{ 'incident_id' => incident.id, 'alert' => 'SearchSuggest5xx', 'devin_session' => true }])
    expect(SlackNotifierService).to have_received(:notify_incident)
      .with(hash_including(session_url: 'https://app.devin.ai/sessions/devin-9', alert_name: 'SearchSuggest5xx'))
  end

  it 'opens the incident without a Devin session when auto-investigate is off' do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(false)

    post :ingest, params: { alerts: [alert] }

    expect(Incident.last.status).to eq('open')
    expect(DevinSessionService).not_to have_received(:create_session)
    expect(SlackNotifierService).to have_received(:notify_incident)
  end

  it 'reports duplicates as skipped' do
    existing = create(:incident, affected_service: 'search-service')
    post :ingest, params: { alerts: [alert] }
    expect(json['incidents']).to eq([{ 'skipped' => true, 'incident_id' => existing.id, 'reason' => 'duplicate' }])
  end

  it 'falls back to the service label and builds a title, description and runbook link' do
    post :ingest, params: { alerts: [alert(labels: { affected_service: '', service: 'file-service', severity: 'bogus' },
                                           annotations: { summary: '', runbook_url: 'https://runbooks/x' })] }

    incident = Incident.last
    expect(incident.affected_service).to eq('file-service')
    expect(incident.severity).to eq('medium')
    expect(incident.title).to eq('SearchSuggest5xx: file-service alert firing')
    expect(incident.description).to include('**Alert**: SearchSuggest5xx', '**Runbook**: https://runbooks/x',
                                            '**Source**: Grafana Unified Alerting')
  end

  it 'maps grafana severities' do
    post :ingest, params: { alerts: [alert(labels: { severity: 'info', dedup: 'false' }),
                                     alert(labels: { severity: 'critical', dedup: 'false' })] }
    expect(Incident.order(:created_at).pluck(:severity)).to contain_exactly('low', 'critical')
  end

  it 'ignores alerts with no affected service or an unknown status' do
    post :ingest, params: { alerts: [alert(labels: { affected_service: '' }), alert(status: 'pending')] }
    expect(json).to include('received' => 2, 'processed' => 0)
    expect(Incident.count).to eq(0)
  end

  it 'drops alerts whose incident fails validation' do
    post :ingest, params: { alerts: [alert(labels: { affected_service: 'not-a-service' })] }
    expect(response).to have_http_status(:ok)
    expect(json['processed']).to eq(0)
    expect(Incident.count).to eq(0)
  end

  describe 'resolved alerts' do
    it 'auto-resolves the active incident for the service' do
      incident = create(:incident, :investigating, affected_service: 'search-service')
      post :ingest, params: { alerts: [alert(status: 'resolved')] }
      expect(incident.reload.status).to eq('resolved')
      expect(json['processed']).to eq(0)
    end

    it 'is a no-op when no incident is active' do
      resolved = create(:incident, :resolved, affected_service: 'search-service')
      post :ingest, params: { alerts: [alert(status: 'resolved')] }
      expect(response).to have_http_status(:ok)
      expect(resolved.reload.status).to eq('resolved')
    end

    it 'is a no-op when the alert has no service' do
      incident = create(:incident, affected_service: 'search-service')
      post :ingest, params: { alerts: [alert(status: 'resolved', labels: { affected_service: '' })] }
      expect(incident.reload.status).to eq('open')
    end

    it 'logs and continues when the transition is rejected' do
      create(:incident, affected_service: 'search-service')
      allow_any_instance_of(Incident).to receive(:resolve!).and_raise(Incident::InvalidTransitionError, 'raced')
      allow(Rails.logger).to receive(:warn)

      post :ingest, params: { alerts: [alert(status: 'resolved')] }

      expect(response).to have_http_status(:ok)
      expect(Rails.logger).to have_received(:warn).with(/Could not auto-resolve incident .*raced/)
    end
  end

  describe 'webhook secret' do
    before { allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return('hook-secret') }

    it 'rejects requests without the secret' do
      post :ingest, params: { alerts: [alert] }
      expect(response).to have_http_status(:unauthorized)
      expect(Incident.count).to eq(0)
    end

    it 'rejects a wrong secret' do
      request.headers['X-Alert-Secret'] = 'nope'
      post :ingest, params: { alerts: [alert] }
      expect(response).to have_http_status(:unauthorized)
    end

    it 'accepts the X-Alert-Secret header' do
      request.headers['X-Alert-Secret'] = 'hook-secret'
      post :ingest, params: { alerts: [alert] }
      expect(response).to have_http_status(:ok)
    end

    it 'accepts a Bearer token' do
      request.headers['Authorization'] = 'Bearer hook-secret'
      post :ingest, params: { alerts: [alert] }
      expect(response).to have_http_status(:ok)
    end
  end
end
