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

    it 'opens one incident and one Devin session for a burst of default alerts' do
      10.times { post :ingest, params: { alerts: [firing_alert] } }

      expect(Incident.where(affected_service: 'file-service').active.count).to eq(1)
      expect(DevinSessionService).to have_received(:create_session).once
      expect(response.parsed_body['incidents'].first['reason']).to eq('duplicate')
    end

    context 'with the per-service incident cap' do
      around do |example|
        previous = ENV.fetch('ALERT_INCIDENT_RATE_LIMIT', nil)
        ENV['ALERT_INCIDENT_RATE_LIMIT'] = '3'
        example.run
      ensure
        ENV['ALERT_INCIDENT_RATE_LIMIT'] = previous
      end

      it 'caps dedup=false alerts per service and skips the Devin session and Slack page' do
        allow(SlackNotifierService).to receive(:notify_incident)

        10.times do
          post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
        end

        expect(Incident.count).to eq(3)
        expect(DevinSessionService).to have_received(:create_session).exactly(3).times
        expect(SlackNotifierService).to have_received(:notify_incident).exactly(3).times
        expect(response.parsed_body['incidents'].first).to include('skipped' => true, 'reason' => 'rate_limited')
      end

      it 'counts resolved incidents so resolving does not reset the cap' do
        3.times do
          post :ingest, params: { alerts: [firing_alert] }
          Incident.active.find_each(&:resolve!)
        end

        post :ingest, params: { alerts: [firing_alert] }

        expect(Incident.count).to eq(3)
        expect(response.parsed_body['incidents'].first['reason']).to eq('rate_limited')
      end

      it 'caps each service independently' do
        3.times { post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] } }

        post :ingest, params: { alerts: [firing_alert(labels: { affected_service: 'auth-service' })] }

        expect(Incident.where(affected_service: 'auth-service').count).to eq(1)
      end

      it 'ignores incidents outside the window and incidents filed by users' do
        2.times do
          Incident.create!(title: 'old', description: 'old', severity: 'high', status: 'resolved',
                           affected_service: 'file-service', created_at: 2.hours.ago)
        end
        Incident.create!(title: 'manual', description: 'manual', severity: 'high', status: 'resolved',
                         affected_service: 'file-service', reporter_id: SecureRandom.uuid)

        3.times { post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] } }

        expect(Incident.where(reporter_id: nil).where('created_at > ?', 1.hour.ago).count).to eq(3)
      end
    end

    it 'falls back to the default cap when the env value is invalid' do
      previous = ENV.fetch('ALERT_INCIDENT_RATE_LIMIT', nil)
      ENV['ALERT_INCIDENT_RATE_LIMIT'] = '0'
      limit = described_class::DEFAULT_INCIDENT_RATE_LIMIT

      (limit + 2).times do
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      end

      expect(Incident.count).to eq(limit)
    ensure
      ENV['ALERT_INCIDENT_RATE_LIMIT'] = previous
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
