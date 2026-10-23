require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  let(:secret) { 'test-alert-secret-0123456789' }
  let(:configured_secret) { secret }

  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(AdminSettingsService).to receive(:reserve_dedup_bypass).and_return(true)
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('ALERT_WEBHOOK_SECRET', nil).and_return(configured_secret)
    request.headers['X-Alert-Secret'] = secret
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

  def resolved_alert
    { status: 'resolved', labels: { alertname: 'FileUploadFailed', affected_service: 'file-service' } }
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

    it 'falls back to normal dedup once the dedup=false budget is spent' do
      allow(ENV).to receive(:fetch).with('ALERT_DEDUP_BYPASS_LIMIT', anything).and_return('2')
      allow(AdminSettingsService).to receive(:reserve_dedup_bypass).and_return(true, true, false, false)

      4.times do
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      end

      expect(Incident.count).to eq(2)
      expect(DevinSessionService).to have_received(:create_session).twice
      expect(AdminSettingsService).to have_received(:reserve_dedup_bypass)
        .with('file-service', limit: 2, window: described_class::DEDUP_BYPASS_WINDOW).exactly(4).times
      expect(response.parsed_body['incidents'].last).to include('skipped' => true, 'reason' => 'duplicate')
    end

    it 'still opens an incident for an over-budget dedup=false alert when none is open' do
      allow(AdminSettingsService).to receive(:reserve_dedup_bypass).and_return(false)
      post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      expect(Incident.count).to eq(1)
    end

    it 'rejects payloads without an alerts array' do
      post :ingest, params: { foo: 'bar' }
      expect(response).to have_http_status(:bad_request)
    end

    it 'rejects oversized alert batches' do
      alerts = Array.new(described_class::MAX_ALERTS_PER_REQUEST + 1) { firing_alert(labels: { dedup: 'false' }) }
      post :ingest, params: { alerts: alerts }
      expect(response).to have_http_status(:payload_too_large)
      expect(Incident.count).to eq(0)
    end

    it 'ignores alerts for services that do not exist' do
      post :ingest, params: { alerts: [firing_alert(labels: { affected_service: 'not-a-service' })] }
      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(0)
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'strips control characters and bounds alert text before storing it' do
      summary = "Disk full\u0000\u001b[31m #{'x' * 500}"
      post :ingest, params: { alerts: [firing_alert(summary: summary)] }

      incident = Incident.last
      expect(incident.title.length).to be <= described_class::MAX_SUMMARY_LENGTH
      expect(incident.title).not_to match(/[\u0000\u001b]/)
      expect(incident.description).not_to match(/[\u0000\u001b]/)
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

    it 'auto-resolves an alert-created incident' do
      post :ingest, params: { alerts: [firing_alert] }
      post :ingest, params: { alerts: [resolved_alert] }
      expect(Incident.last.status).to eq('resolved')
    end

    it 'does not auto-resolve an incident a person reported' do
      incident = Incident.create!(title: 'Uploads broken', description: 'reported by support',
                                  severity: 'high', status: 'open', affected_service: 'file-service',
                                  reporter_id: SecureRandom.uuid)

      post :ingest, params: { alerts: [resolved_alert] }

      expect(incident.reload.status).to eq('open')
    end

    context 'webhook authentication' do
      it 'accepts the secret as an Authorization Bearer token' do
        request.headers['X-Alert-Secret'] = nil
        request.headers['Authorization'] = "Bearer #{secret}"
        post :ingest, params: { alerts: [firing_alert] }
        expect(response).to have_http_status(:ok)
        expect(Incident.count).to eq(1)
      end

      it 'rejects a request without the secret' do
        request.headers['X-Alert-Secret'] = nil
        post :ingest, params: { alerts: [firing_alert] }
        expect(response).to have_http_status(:unauthorized)
        expect(Incident.count).to eq(0)
      end

      it 'rejects a wrong secret' do
        request.headers['X-Alert-Secret'] = 'wrong'
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
        expect(response).to have_http_status(:unauthorized)
        expect(DevinSessionService).not_to have_received(:create_session)
      end

      it 'rejects a forged resolve without the secret' do
        post :ingest, params: { alerts: [firing_alert] }
        request.headers['X-Alert-Secret'] = nil
        post :ingest, params: { alerts: [resolved_alert] }
        expect(response).to have_http_status(:unauthorized)
        expect(Incident.last.status).to eq('investigating')
      end

      context 'when ALERT_WEBHOOK_SECRET is unset' do
        let(:configured_secret) { nil }

        it 'fails closed' do
          request.headers['X-Alert-Secret'] = nil
          post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
          expect(response).to have_http_status(:service_unavailable)
          expect(Incident.count).to eq(0)
          expect(DevinSessionService).not_to have_received(:create_session)
        end
      end

      context 'when ALERT_WEBHOOK_SECRET is the retired committed default' do
        let(:configured_secret) { 'demo-alert-secret' }
        let(:secret) { 'demo-alert-secret' }

        it 'fails closed even when the caller sends it' do
          post :ingest, params: { alerts: [firing_alert] }
          expect(response).to have_http_status(:service_unavailable)
          expect(Incident.count).to eq(0)
        end
      end
    end
  end
end
