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

    context 'with a slack_listener route' do
      let(:alert) do
        firing_alert(
          labels: { alertname: 'DocumentCreateFailed', affected_service: 'document-service', dedup: 'false' },
          summary: 'Document creation failed: Untitled document'
        )
      end

      it 'leaves the Devin session to the Slack listener once the bot post lands' do
        allow(SlackNotifierService).to receive(:notify_incident).and_return(true)

        2.times { post :ingest, params: { alerts: [alert] } }

        expect(Incident.count).to eq(2)
        expect(DevinSessionService).not_to have_received(:create_session)
        expect(SlackNotifierService).to have_received(:notify_incident)
          .with(hash_including(alert_name: 'DocumentCreateFailed', devin_listener: true)).twice
        expect(SlackNotifierService).not_to have_received(:notify_incident)
          .with(hash_excluding(devin_listener: true))
      end

      it 'falls back to an API session and a regular notification when the bot post fails' do
        allow(SlackNotifierService).to receive(:notify_incident).and_return(false)

        post :ingest, params: { alerts: [alert] }

        expect(DevinSessionService).to have_received(:create_session).once
        expect(SlackNotifierService).to have_received(:notify_incident)
          .with(hash_including(devin_listener: true)).once
        expect(SlackNotifierService).to have_received(:notify_incident)
          .with(hash_excluding(devin_listener: true)).once
      end

      it 'does not hand the alert to the listener when auto-investigate is disabled' do
        allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(false)
        allow(SlackNotifierService).to receive(:notify_incident)

        post :ingest, params: { alerts: [alert] }

        expect(DevinSessionService).not_to have_received(:create_session)
        expect(SlackNotifierService).not_to have_received(:notify_incident)
          .with(hash_including(devin_listener: true))
        expect(SlackNotifierService).to have_received(:notify_incident)
          .with(hash_including(alert_name: 'DocumentCreateFailed')).once
      end
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
