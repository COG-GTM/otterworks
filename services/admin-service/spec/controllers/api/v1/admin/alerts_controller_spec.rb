require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  let(:alert_secret) { 'test-alert-secret' }

  around do |example|
    original = ENV.fetch('ALERT_WEBHOOK_SECRET', nil)
    ENV['ALERT_WEBHOOK_SECRET'] = alert_secret
    example.run
  ensure
    ENV['ALERT_WEBHOOK_SECRET'] = original
  end

  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
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
  end

  describe 'webhook secret verification' do
    it 'rejects requests with no secret' do
      request.headers['X-Alert-Secret'] = nil
      post :ingest, params: { alerts: [firing_alert] }
      expect(response).to have_http_status(:unauthorized)
      expect(Incident.count).to eq(0)
    end

    it 'rejects requests with the wrong secret' do
      request.headers['X-Alert-Secret'] = 'wrong-secret'
      post :ingest, params: { alerts: [firing_alert] }
      expect(response).to have_http_status(:unauthorized)
      expect(Incident.count).to eq(0)
    end

    it 'accepts the secret as a Grafana-style Bearer token' do
      request.headers['X-Alert-Secret'] = nil
      request.headers['Authorization'] = "Bearer #{alert_secret}"
      post :ingest, params: { alerts: [firing_alert] }
      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(1)
    end

    [nil, ''].each do |unset|
      it "fails closed when ALERT_WEBHOOK_SECRET is #{unset.inspect}" do
        ENV['ALERT_WEBHOOK_SECRET'] = unset
        request.headers['X-Alert-Secret'] = nil
        post :ingest, params: { alerts: [firing_alert] }
        expect(response).to have_http_status(:service_unavailable)
        expect(Incident.count).to eq(0)
        expect(DevinSessionService).not_to have_received(:create_session)
      end
    end

    it 'does not resolve incidents for unauthenticated resolved alerts' do
      incident = Incident.create!(title: 'Real outage', description: 'outage', severity: 'high', status: 'open',
                                  affected_service: 'file-service')
      request.headers['X-Alert-Secret'] = nil
      post :ingest, params: { alerts: [firing_alert.merge(status: 'resolved')] }
      expect(response).to have_http_status(:unauthorized)
      expect(incident.reload.status).to eq('open')
    end
  end
end
