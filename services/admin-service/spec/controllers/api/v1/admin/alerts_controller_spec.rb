require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  let(:alert_secret) { 'test-alert-secret-0123456789abcdef' }

  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return(alert_secret)
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

  describe 'alert secret verification' do
    it 'accepts the secret as an Authorization: Bearer token' do
      request.headers['X-Alert-Secret'] = nil
      request.headers['Authorization'] = "Bearer #{alert_secret}"
      post :ingest, params: { alerts: [firing_alert] }
      expect(response).to have_http_status(:ok)
    end

    it 'rejects a request with the wrong secret' do
      request.headers['X-Alert-Secret'] = 'wrong'
      post :ingest, params: { alerts: [firing_alert] }
      expect(response).to have_http_status(:unauthorized)
      expect(Incident.count).to eq(0)
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'rejects a request with no secret' do
      request.headers['X-Alert-Secret'] = nil
      post :ingest, params: { alerts: [firing_alert] }
      expect(response).to have_http_status(:unauthorized)
      expect(Incident.count).to eq(0)
    end

    [nil, '', '   '].each do |unset|
      it "fails closed when ALERT_WEBHOOK_SECRET is #{unset.inspect}" do
        allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return(unset)
        request.headers['X-Alert-Secret'] = unset
        post :ingest, params: { alerts: [firing_alert] }
        expect(response).to have_http_status(:service_unavailable)
        expect(Incident.count).to eq(0)
        expect(DevinSessionService).not_to have_received(:create_session)
      end
    end

    it 'fails closed when ALERT_WEBHOOK_SECRET is the old committed default' do
      allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return('demo-alert-secret')
      request.headers['X-Alert-Secret'] = 'demo-alert-secret'
      post :ingest, params: { alerts: [firing_alert] }
      expect(response).to have_http_status(:service_unavailable)
      expect(Incident.count).to eq(0)
    end
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
