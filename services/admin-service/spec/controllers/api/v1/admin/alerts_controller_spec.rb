require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  let(:alert_secret) { 'test-alert-secret-0123456789abcdef' }

  around do |example|
    previous = ENV.fetch('ALERT_WEBHOOK_SECRET', nil)
    ENV['ALERT_WEBHOOK_SECRET'] = alert_secret
    example.run
  ensure
    previous.nil? ? ENV.delete('ALERT_WEBHOOK_SECRET') : ENV['ALERT_WEBHOOK_SECRET'] = previous
  end

  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(SlackNotifierService).to receive(:notify_incident)
    allow(AlertIngestBudget).to receive(:allow_dedup_bypass?).and_return(true)
    request.headers['X-Alert-Secret'] = alert_secret
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

    it 'rejects batches larger than MAX_ALERTS_PER_REQUEST' do
      alerts = Array.new(described_class::MAX_ALERTS_PER_REQUEST + 1) { firing_alert(labels: { dedup: 'false' }) }
      post :ingest, params: { alerts: alerts }
      expect(response).to have_http_status(:payload_too_large)
      expect(Incident.count).to eq(0)
    end

    it 'falls back to de-duplication once the dedup=false budget is spent' do
      allow(AlertIngestBudget).to receive(:allow_dedup_bypass?).and_return(true, false, false)
      3.times do
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      end
      expect(Incident.count).to eq(1)
      expect(DevinSessionService).to have_received(:create_session).once
    end

    it 'truncates an oversized summary to a valid incident title' do
      post :ingest, params: { alerts: [firing_alert(summary: 'x' * 1_000)] }
      expect(Incident.count).to eq(1)
      expect(Incident.last.title.length).to be <= 255
    end
  end

  describe 'alert secret verification' do
    def forged_alerts
      { alerts: [{ status: 'firing', labels: { alertname: 'Forged', severity: 'critical', affected_service: 'file-service' },
                   annotations: { summary: 'forged' } }] }
    end

    def expect_rejected(status)
      post :ingest, params: forged_alerts
      expect(response).to have_http_status(status)
      expect(Incident.count).to eq(0)
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'fails closed when ALERT_WEBHOOK_SECRET is unset' do
      ENV.delete('ALERT_WEBHOOK_SECRET')
      expect_rejected(:service_unavailable)
    end

    it 'fails closed when ALERT_WEBHOOK_SECRET is blank' do
      ENV['ALERT_WEBHOOK_SECRET'] = '  '
      request.headers['X-Alert-Secret'] = '  '
      expect_rejected(:service_unavailable)
    end

    it 'rejects the retired public default even when the caller sends it' do
      ENV['ALERT_WEBHOOK_SECRET'] = 'demo-alert-secret'
      request.headers['X-Alert-Secret'] = 'demo-alert-secret'
      expect_rejected(:service_unavailable)
    end

    it 'rejects requests with no credential' do
      request.headers['X-Alert-Secret'] = nil
      expect_rejected(:unauthorized)
    end

    it 'rejects a wrong secret' do
      request.headers['X-Alert-Secret'] = 'demo-alert-secret'
      expect_rejected(:unauthorized)
    end

    it 'does not let an unauthenticated resolved alert close an open incident' do
      incident = Incident.create!(title: 't', description: 'd', severity: 'high',
                                  status: 'investigating', affected_service: 'file-service')
      request.headers['X-Alert-Secret'] = nil
      post :ingest, params: { alerts: [{ status: 'resolved', labels: { alertname: 'Forged', affected_service: 'file-service' } }] }
      expect(response).to have_http_status(:unauthorized)
      expect(incident.reload.status).to eq('investigating')
    end

    it 'accepts the secret as a Grafana Bearer token' do
      request.headers['X-Alert-Secret'] = nil
      request.headers['Authorization'] = "Bearer #{alert_secret}"
      post :ingest, params: forged_alerts
      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(1)
    end

    it 'rejects a non-Bearer Authorization header carrying the secret' do
      request.headers['X-Alert-Secret'] = nil
      request.headers['Authorization'] = "Basic #{alert_secret}"
      expect_rejected(:unauthorized)
    end
  end
end
