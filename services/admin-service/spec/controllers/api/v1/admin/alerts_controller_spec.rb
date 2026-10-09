require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  let(:secret) { 'test-alert-secret' }

  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(SlackNotifierService).to receive(:notify_incident)
  end

  around do |example|
    previous = ENV.fetch('ALERT_WEBHOOK_SECRET', nil)
    example.run
  ensure
    previous.nil? ? ENV.delete('ALERT_WEBHOOK_SECRET') : ENV['ALERT_WEBHOOK_SECRET'] = previous
  end

  def firing_alert(labels: {}, summary: 'File upload failed: a.txt', service: 'file-service')
    {
      status: 'firing',
      labels: {
        alertname: 'FileUploadFailed',
        severity: 'critical',
        affected_service: service
      }.merge(labels),
      annotations: { summary: summary, description: summary }
    }
  end

  def as_trusted_sender
    ENV['ALERT_WEBHOOK_SECRET'] = secret
    request.headers['X-Alert-Secret'] = secret
  end

  def as_unauthenticated_sender
    ENV.delete('ALERT_WEBHOOK_SECRET')
  end

  describe 'POST #ingest' do
    before { as_trusted_sender }

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

    it 'creates one incident per alert when a trusted sender sets dedup=false' do
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
      post :ingest, params: { alerts: [firing_alert(labels: { reporter_email: 'preston@example.com' })] }

      expect(SlackNotifierService).to have_received(:notify_incident)
        .with(hash_including(reporter_email: 'preston@example.com'))
    end

    it 'passes a nil reporter_email when the alert has no reporter label' do
      post :ingest, params: { alerts: [firing_alert] }

      expect(SlackNotifierService).to have_received(:notify_incident)
        .with(hash_including(reporter_email: nil))
    end

    describe 'alerts-per-request cap' do
      it 'rejects payloads with more than MAX_ALERTS_PER_REQUEST alerts without side effects' do
        alerts = Array.new(described_class::MAX_ALERTS_PER_REQUEST + 1) { firing_alert(labels: { dedup: 'false' }) }

        post :ingest, params: { alerts: alerts }

        expect(response).to have_http_status(:payload_too_large)
        expect(Incident.count).to eq(0)
        expect(DevinSessionService).not_to have_received(:create_session)
        expect(SlackNotifierService).not_to have_received(:notify_incident)
      end

      it 'accepts exactly MAX_ALERTS_PER_REQUEST alerts' do
        alerts = Array.new(described_class::MAX_ALERTS_PER_REQUEST) { firing_alert }

        post :ingest, params: { alerts: alerts }

        expect(response).to have_http_status(:ok)
        expect(response.parsed_body['received']).to eq(described_class::MAX_ALERTS_PER_REQUEST)
      end
    end

    describe 'sender authentication' do
      it 'rejects a wrong secret when ALERT_WEBHOOK_SECRET is configured' do
        request.headers['X-Alert-Secret'] = 'wrong'
        post :ingest, params: { alerts: [firing_alert] }
        expect(response).to have_http_status(:unauthorized)
        expect(Incident.count).to eq(0)
      end

      it 'accepts the secret as an Authorization Bearer token' do
        request.headers['X-Alert-Secret'] = nil
        request.headers['Authorization'] = "Bearer #{secret}"
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
        expect(Incident.count).to eq(2)
      end
    end

    context 'when ALERT_WEBHOOK_SECRET is unset (unauthenticated ingest)' do
      before { as_unauthenticated_sender }

      it 'still accepts alerts' do
        post :ingest, params: { alerts: [firing_alert] }
        expect(response).to have_http_status(:ok)
        expect(Incident.count).to eq(1)
      end

      it 'ignores dedup=false and collapses alerts onto the open incident' do
        alerts = Array.new(5) { firing_alert(labels: { dedup: 'false' }) }

        post :ingest, params: { alerts: alerts }

        expect(Incident.count).to eq(1)
        expect(DevinSessionService).to have_received(:create_session).once
        expect(SlackNotifierService).to have_received(:notify_incident).once
        expect(response.parsed_body['incidents'].count { |i| i['reason'] == 'duplicate' }).to eq(4)
      end

      it 'drops the reporter_email label' do
        post :ingest, params: { alerts: [firing_alert(labels: { reporter_email: 'victim@example.com' })] }

        expect(SlackNotifierService).to have_received(:notify_incident)
          .with(hash_including(reporter_email: nil))
      end
    end

    describe 'per-service budgets' do
      it 'stops honouring dedup=false once the incident budget is spent' do
        allow(AlertBudget).to receive(:max_incidents_per_service).and_return(2)

        4.times { post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] } }

        expect(Incident.count).to eq(2)
        expect(response.parsed_body['incidents'].first['reason']).to eq('duplicate')
      end

      it 'stops starting Devin sessions once the session budget is spent' do
        allow(AlertBudget).to receive(:max_devin_sessions_per_service).and_return(2)
        counter = 0
        allow(DevinSessionService).to receive(:create_session) do
          counter += 1
          { session_id: "devin-#{counter}", url: "https://app.devin.ai/sessions/#{counter}" }
        end

        4.times { post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] } }

        expect(Incident.count).to eq(4)
        expect(DevinSessionService).to have_received(:create_session).twice
        expect(Incident.where.not(devin_session_id: nil).count).to eq(2)
        expect(SlackNotifierService).to have_received(:notify_incident).exactly(4).times
      end

      it 'caps incident creation even when resolved alerts leave nothing to dedupe onto' do
        allow(AlertBudget).to receive(:max_incidents_per_service).and_return(2)
        resolved = firing_alert.merge(status: 'resolved')

        3.times do
          post :ingest, params: { alerts: [firing_alert] }
          post :ingest, params: { alerts: [resolved] }
        end
        post :ingest, params: { alerts: [firing_alert] }

        expect(Incident.count).to eq(2)
        expect(response.parsed_body['incidents'].first).to include('skipped' => true, 'reason' => 'budget_exhausted')
      end

      it 'does not count Devin sessions started outside alert ingest' do
        allow(AlertBudget).to receive(:max_devin_sessions_per_service).and_return(1)
        Incident.create!(title: 'manual', description: 'd', severity: 'high', status: 'resolved',
                         affected_service: 'file-service', devin_session_id: 'manual-1')

        post :ingest, params: { alerts: [firing_alert] }

        expect(DevinSessionService).to have_received(:create_session).once
      end

      it 'ignores alerts for unknown services without reserving budget' do
        post :ingest, params: { alerts: [firing_alert(service: 'not-a-service')] }

        expect(Incident.count).to eq(0)
        expect(AlertBudgetReservation.count).to eq(0)
      end

      it 'budgets each service separately' do
        allow(AlertBudget).to receive(:max_devin_sessions_per_service).and_return(1)
        allow(DevinSessionService).to receive(:create_session) do |incident:|
          { session_id: "devin-#{incident.id}", url: "https://app.devin.ai/sessions/#{incident.id}" }
        end

        post :ingest, params: { alerts: [firing_alert(service: 'file-service')] }
        post :ingest, params: { alerts: [firing_alert(service: 'search-service')] }

        expect(DevinSessionService).to have_received(:create_session).twice
      end
    end
  end
end
