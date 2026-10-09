require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  let(:alert_secret) { 'test-alert-secret' }

  before do
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return(alert_secret)
    request.headers['X-Alert-Secret'] = alert_secret
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(DevinSessionThrottle).to receive(:acquire).and_return(true)
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

  describe 'webhook secret' do
    it 'rejects every request when ALERT_WEBHOOK_SECRET is unset' do
      allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return(nil)

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:service_unavailable)
      expect(Incident.count).to eq(0)
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'rejects every request when ALERT_WEBHOOK_SECRET is blank' do
      allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return('  ')
      request.headers['X-Alert-Secret'] = '  '

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:service_unavailable)
      expect(Incident.count).to eq(0)
    end

    it 'rejects a missing secret' do
      request.headers['X-Alert-Secret'] = nil

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:unauthorized)
      expect(Incident.count).to eq(0)
    end

    it 'rejects a wrong secret' do
      request.headers['X-Alert-Secret'] = 'not-the-secret'

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:unauthorized)
      expect(Incident.count).to eq(0)
    end

    it 'accepts the secret as a Grafana Bearer token' do
      request.headers['X-Alert-Secret'] = nil
      request.headers['Authorization'] = "Bearer #{alert_secret}"

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(1)
    end

    it 'does not let a forged resolved alert close incidents without the secret' do
      incident = Incident.create!(title: 't', description: 'd', severity: 'high', status: 'open',
                                  affected_service: 'file-service')
      request.headers['X-Alert-Secret'] = 'not-the-secret'

      post :ingest, params: { alerts: [{ status: 'resolved', labels: { affected_service: 'file-service' } }] }

      expect(response).to have_http_status(:unauthorized)
      expect(incident.reload.status).to eq('open')
    end
  end

  describe 'POST #ingest' do
    it 'rejects batches larger than MAX_ALERTS_PER_REQUEST' do
      alerts = Array.new(described_class::MAX_ALERTS_PER_REQUEST + 1) { firing_alert(labels: { dedup: 'false' }) }

      post :ingest, params: { alerts: alerts }

      expect(response).to have_http_status(413)
      expect(Incident.count).to eq(0)
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'opens the incident but skips the Devin session once the hourly limit is reached' do
      allow(DevinSessionThrottle).to receive(:acquire).and_return(false)

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(1)
      expect(Incident.last.status).to eq('open')
      expect(DevinSessionService).not_to have_received(:create_session)
    end

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

    it 'ignores a client-supplied dedup=false label' do
      3.times do
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      end
      expect(Incident.count).to eq(1)
      expect(DevinSessionService).to have_received(:create_session).once
    end

    it 'dedupes a batch of alerts for the same service into one incident' do
      post :ingest, params: { alerts: Array.new(5) { firing_alert(labels: { dedup: 'false' }) } }
      expect(Incident.count).to eq(1)
      expect(DevinSessionService).to have_received(:create_session).once
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
