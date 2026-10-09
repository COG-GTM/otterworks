require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(ENV).to receive(:fetch).and_call_original
    stub_env('ALERT_WEBHOOK_SECRET', nil)
    stub_env('DEVIN_AUTO_INVESTIGATE_ALERTNAMES', nil)
    stub_env('ALERT_RUNBOOK_URL_HOSTS', nil)
  end

  def stub_env(name, value)
    allow(ENV).to receive(:fetch).with(name, nil).and_return(value)
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

  describe 'ingest authentication' do
    it 'rejects gateway-relayed requests when no secret is configured' do
      request.headers['X-Forwarded-For'] = '203.0.113.7'
      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:unauthorized)
      expect(Incident.count).to eq(0)
    end

    it 'rejects a wrong secret' do
      stub_env('ALERT_WEBHOOK_SECRET', 's3cret')
      request.headers['X-Alert-Secret'] = 'nope'
      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:unauthorized)
    end

    it 'rejects a missing secret when one is configured' do
      stub_env('ALERT_WEBHOOK_SECRET', 's3cret')
      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:unauthorized)
    end

    it 'accepts the configured secret as a Bearer token, even via a proxy' do
      stub_env('ALERT_WEBHOOK_SECRET', 's3cret')
      request.headers['Authorization'] = 'Bearer s3cret'
      request.headers['X-Forwarded-For'] = '10.0.0.5'
      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(1)
    end
  end

  describe 'auto-investigate allowlist' do
    it 'opens an incident without a Devin session for unlisted alert types' do
      post :ingest, params: { alerts: [firing_alert(labels: { alertname: 'AttackerChosen' })] }

      expect(Incident.last.status).to eq('open')
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'honours DEVIN_AUTO_INVESTIGATE_ALERTNAMES' do
      stub_env('DEVIN_AUTO_INVESTIGATE_ALERTNAMES', 'CustomAlert, Other')
      post :ingest, params: { alerts: [firing_alert(labels: { alertname: 'CustomAlert', dedup: 'false' })] }
      post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }

      expect(DevinSessionService).to have_received(:create_session).once
    end
  end

  describe 'runbook links' do
    def alert_with_runbook(url)
      firing_alert.tap { |a| a[:annotations][:runbook_url] = url }
    end

    it 'drops runbook URLs when no hosts are allowlisted' do
      post :ingest, params: { alerts: [alert_with_runbook('https://evil.example/run')] }

      expect(Incident.last.description).not_to include('evil.example')
    end

    it 'keeps https runbook URLs on allowlisted hosts only' do
      stub_env('ALERT_RUNBOOK_URL_HOSTS', 'runbooks.otterworks.app')
      post :ingest, params: { alerts: [alert_with_runbook('https://runbooks.otterworks.app/upload')] }
      expect(Incident.last.description).to include('**Runbook**: https://runbooks.otterworks.app/upload')

      evil = alert_with_runbook('https://evil.example/run').tap { |a| a[:labels][:dedup] = 'false' }
      post :ingest, params: { alerts: [evil] }
      expect(Incident.last.description).not_to include('evil.example')
    end
  end
end
