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

    it 'does not auto-start a Devin session for alerts outside the allowlist' do
      post :ingest, params: { alerts: [firing_alert(labels: { alertname: 'AttackerChosenAlert' })] }
      expect(Incident.count).to eq(1)
      expect(Incident.last.status).to eq('open')
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'still triages an allowlisted alert when a non-allowlisted one already opened an incident' do
      post :ingest, params: { alerts: [firing_alert(labels: { alertname: 'AttackerChosenAlert' })] }
      post :ingest, params: { alerts: [firing_alert] }
      post :ingest, params: { alerts: [firing_alert] }
      expect(Incident.count).to eq(2)
      expect(DevinSessionService).to have_received(:create_session).once
    end

    it 'honors ALERT_AUTO_INVESTIGATE_ALERTNAMES when set' do
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('ALERT_AUTO_INVESTIGATE_ALERTNAMES', '').and_return('CustomAlert')

      post :ingest, params: { alerts: [firing_alert(labels: { alertname: 'CustomAlert', dedup: 'false' })] }
      post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      expect(DevinSessionService).to have_received(:create_session).once
    end

    it 'matches ALERT_RUNBOOK_HOSTS case-insensitively' do
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('ALERT_RUNBOOK_HOSTS', '').and_return('Docs.Example.com')
      alert = firing_alert.deep_merge(annotations: { runbook_url: 'https://docs.example.com/rb' })

      post :ingest, params: { alerts: [alert] }
      expect(Incident.last.description).to include('https://docs.example.com/rb')
    end

    it 'keeps runbook links only for allowlisted https hosts' do
      alert = firing_alert(labels: { dedup: 'false' })
      good = alert.deep_merge(annotations: { runbook_url: 'https://docs.otterworks.dev/runbooks/service-down' })
      bad = alert.deep_merge(annotations: { runbook_url: 'https://evil.example/payload' })
      post :ingest, params: { alerts: [good, bad] }

      good_incident, bad_incident = Incident.order(:created_at).last(2)
      expect(good_incident.description).to include('https://docs.otterworks.dev/runbooks/service-down')
      expect(bad_incident.description).not_to include('evil.example')
    end
  end
end
