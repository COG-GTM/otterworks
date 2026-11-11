require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  include ActiveSupport::Testing::TimeHelpers

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

    it 'rejects payloads with more alerts than the per-request cap' do
      alerts = Array.new(described_class::MAX_ALERTS_PER_REQUEST + 1) { firing_alert(labels: { dedup: 'false' }) }
      post :ingest, params: { alerts: alerts }, as: :json
      expect(response).to have_http_status(413)
      expect(Incident.count).to eq(0)
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'accepts payloads at the per-request cap' do
      alerts = Array.new(described_class::MAX_ALERTS_PER_REQUEST) { firing_alert }
      post :ingest, params: { alerts: alerts }, as: :json
      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(1)
    end

    it 'stops honoring dedup=false once the per-service budget is spent' do
      limit = described_class::DEDUP_BYPASS_LIMIT
      (limit + 3).times do
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      end
      expect(Incident.where(affected_service: 'file-service').count).to eq(limit)
      expect(DevinSessionService).to have_received(:create_session).exactly(limit).times
      expect(response.parsed_body['incidents'].first['reason']).to eq('duplicate')
    end

    it 'budgets dedup=false per service' do
      described_class::DEDUP_BYPASS_LIMIT.times do
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      end
      post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false', affected_service: 'auth-service' })] }
      expect(Incident.where(affected_service: 'auth-service').count).to eq(1)
    end

    it 'restores the dedup=false budget once the window passes' do
      described_class::DEDUP_BYPASS_LIMIT.times do
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      end
      travel(described_class::DEDUP_BYPASS_WINDOW + 1.second) do
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      end
      expect(Incident.count).to eq(described_class::DEDUP_BYPASS_LIMIT + 1)
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
