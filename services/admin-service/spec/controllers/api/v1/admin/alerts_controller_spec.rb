require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  let(:alert_secret) { 'test-alert-secret-0123456789abcdef' }
  let(:configured_secret) { alert_secret }

  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return(configured_secret)
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

  describe 'authentication' do
    context 'when ALERT_WEBHOOK_SECRET is not configured' do
      let(:configured_secret) { nil }

      it 'rejects the request and creates no incident' do
        post :ingest, params: { alerts: [firing_alert] }
        expect(response).to have_http_status(:unauthorized)
        expect(Incident.count).to eq(0)
        expect(DevinSessionService).not_to have_received(:create_session)
      end
    end

    context 'when ALERT_WEBHOOK_SECRET is blank' do
      let(:configured_secret) { '' }

      it 'rejects the request even with an empty secret header' do
        request.headers['X-Alert-Secret'] = ''
        post :ingest, params: { alerts: [firing_alert] }
        expect(response).to have_http_status(:unauthorized)
        expect(Incident.count).to eq(0)
      end
    end

    context 'when ALERT_WEBHOOK_SECRET is the old public compose default' do
      let(:configured_secret) { 'demo-alert-secret' }
      let(:alert_secret) { 'demo-alert-secret' }

      it 'treats it as unconfigured' do
        post :ingest, params: { alerts: [firing_alert] }
        expect(response).to have_http_status(:unauthorized)
        expect(Incident.count).to eq(0)
      end
    end

    it 'rejects a wrong X-Alert-Secret' do
      request.headers['X-Alert-Secret'] = 'wrong-secret'
      post :ingest, params: { alerts: [firing_alert] }
      expect(response).to have_http_status(:unauthorized)
      expect(Incident.count).to eq(0)
    end

    it 'rejects a request carrying only a user JWT' do
      request.headers['X-Alert-Secret'] = nil
      request.headers['Authorization'] = 'Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.sig'
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

    it 'marks incidents it creates as alert-sourced' do
      post :ingest, params: { alerts: [firing_alert] }
      expect(Incident.last.source).to eq(Incident::SOURCE_ALERT)
    end

    it 'caps dedup=false incidents per service per hour' do
      allow(ENV).to receive(:fetch).with('ALERT_MAX_INCIDENTS_PER_SERVICE_PER_HOUR', '').and_return('2')

      3.times do
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      end

      expect(Incident.count).to eq(2)
      expect(DevinSessionService).to have_received(:create_session).twice
      expect(response.parsed_body['incidents'].first).to include('skipped' => true, 'reason' => 'rate_limited')
    end

    it 'does not count incidents older than an hour against the cap' do
      allow(ENV).to receive(:fetch).with('ALERT_MAX_INCIDENTS_PER_SERVICE_PER_HOUR', '').and_return('1')
      Incident.create!(title: 'old', description: 'old', affected_service: 'file-service',
                       source: Incident::SOURCE_ALERT, status: 'resolved', created_at: 2.hours.ago)

      post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }

      expect(Incident.count).to eq(2)
    end

    it 'resolves the open alert-created incident for the service' do
      post :ingest, params: { alerts: [firing_alert] }
      post :ingest, params: { alerts: [firing_alert.merge(status: 'resolved')] }
      expect(Incident.last.status).to eq('resolved')
    end

    it 'does not resolve manually filed incidents' do
      manual = Incident.create!(title: 'Uploads failing', description: 'filed by on-call',
                                affected_service: 'file-service', status: 'open')

      post :ingest, params: { alerts: [firing_alert.merge(status: 'resolved')] }

      expect(manual.reload.status).to eq('open')
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
