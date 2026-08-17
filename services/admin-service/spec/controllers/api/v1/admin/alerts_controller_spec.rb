require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  let(:session_payload) { { session_id: 'devin-7', url: 'https://app.devin.ai/sessions/devin-7' } }

  def firing_alert(overrides = {})
    {
      status: 'firing',
      labels: { alertname: 'HighErrorRate', severity: 'critical', affected_service: 'file-service' },
      annotations: { summary: 'file-service 5xx rate is high', description: 'error ratio above 5%' }
    }.deep_merge(overrides)
  end

  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
  end

  describe 'POST #ingest' do
    it 'creates an investigating incident and reports it back' do
      allow(DevinSessionService).to receive(:create_session).and_return(session_payload)

      expect { post :ingest, params: { alerts: [firing_alert] } }.to change(Incident, :count).by(1)

      expect(response).to have_http_status(:ok)
      body = JSON.parse(response.body)
      expect(body).to include('received' => 1, 'processed' => 1)
      expect(body['incidents'].first).to include('alert' => 'HighErrorRate', 'devin_session' => true)

      incident = Incident.last
      expect(incident).to have_attributes(
        title: 'file-service 5xx rate is high',
        severity: 'critical',
        status: 'investigating',
        affected_service: 'file-service',
        devin_session_id: 'devin-7',
        devin_session_status: 'running',
        reporter_id: nil
      )
      expect(incident.description).to include('error ratio above 5%', '**Alert**: HighErrorRate',
                                              '**Source**: Grafana Unified Alerting')
    end

    it 'maps Grafana severities onto incident severities' do
      post :ingest, params: {
        alerts: [
          firing_alert(labels: { severity: 'warning', affected_service: 'auth-service' }),
          firing_alert(labels: { severity: 'weird', affected_service: 'search-service' }),
          firing_alert(labels: { severity: 'info', affected_service: 'audit-service' })
        ]
      }

      expect(Incident.find_by(affected_service: 'auth-service').severity).to eq('medium')
      expect(Incident.find_by(affected_service: 'search-service').severity).to eq('medium')
      expect(Incident.find_by(affected_service: 'audit-service').severity).to eq('low')
    end

    it 'falls back to the service label and a generated title/description' do
      post :ingest, params: {
        alerts: [{ status: 'firing', labels: { alertname: 'PodDown', severity: 'high', service: 'collab-service' },
                   annotations: { runbook_url: 'https://runbooks/pod-down' } }]
      }

      incident = Incident.last
      expect(incident.affected_service).to eq('collab-service')
      expect(incident.title).to eq('PodDown: collab-service alert firing')
      expect(incident.description).to include('**Runbook**: https://runbooks/pod-down')
    end

    it 'leaves the incident open and skips Devin when auto-investigate is off' do
      allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(false)

      post :ingest, params: { alerts: [firing_alert] }

      expect(Incident.last.status).to eq('open')
      expect(Incident.last.devin_session_id).to be_nil
      expect(DevinSessionService).not_to have_received(:create_session)
      expect(JSON.parse(response.body)['incidents'].first['devin_session']).to be(false)
    end

    it 'deduplicates against an already open incident for the service' do
      existing = create(:incident, status: 'open', affected_service: 'file-service')

      expect { post :ingest, params: { alerts: [firing_alert] } }.not_to change(Incident, :count)

      expect(JSON.parse(response.body)['incidents'].first)
        .to include('skipped' => true, 'incident_id' => existing.id, 'reason' => 'duplicate')
    end

    it 'auto-resolves the open incident when the alert resolves' do
      incident = create(:incident, :investigating, affected_service: 'file-service')

      post :ingest, params: { alerts: [firing_alert(status: 'resolved')] }

      expect(incident.reload.status).to eq('resolved')
      expect(JSON.parse(response.body)).to include('received' => 1, 'processed' => 0)
    end

    it 'ignores a resolved alert with no matching incident' do
      expect { post :ingest, params: { alerts: [firing_alert(status: 'resolved')] } }.not_to raise_error

      expect(JSON.parse(response.body)['processed']).to eq(0)
    end

    it 'ignores a resolved alert without an affected service' do
      post :ingest, params: { alerts: [{ status: 'resolved', labels: { alertname: 'X' } }] }

      expect(JSON.parse(response.body)['processed']).to eq(0)
    end

    it 'warns instead of raising when the incident cannot be auto-resolved' do
      create(:incident, :investigating, affected_service: 'file-service')
      allow_any_instance_of(Incident).to receive(:resolve!).and_raise(Incident::InvalidTransitionError, 'closed')
      allow(Rails.logger).to receive(:warn)

      post :ingest, params: { alerts: [firing_alert(status: 'resolved')] }

      expect(response).to have_http_status(:ok)
      expect(Rails.logger).to have_received(:warn).with(/Could not auto-resolve incident/)
    end

    it 'skips alerts that are neither firing nor resolved' do
      expect { post :ingest, params: { alerts: [firing_alert(status: 'pending')] } }.not_to change(Incident, :count)

      expect(JSON.parse(response.body)['processed']).to eq(0)
    end

    it 'skips firing alerts without an affected service' do
      expect do
        post :ingest, params: { alerts: [{ status: 'firing', labels: { alertname: 'Nameless' } }] }
      end.not_to change(Incident, :count)
    end

    it 'logs and skips an alert whose incident fails validation' do
      allow(Incident).to receive(:create!).and_raise(ActiveRecord::RecordInvalid.new(Incident.new))
      allow(Rails.logger).to receive(:error)

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['processed']).to eq(0)
      expect(Rails.logger).to have_received(:error).with(/Failed to create incident from alert HighErrorRate/)
    end

    it 'returns 400 when the alerts array is missing' do
      post :ingest, params: { receiver: 'otterworks-webhook' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Missing alerts array')
    end
  end

  describe 'webhook secret verification' do
    before { stub_const('ENV', ENV.to_hash.merge('ALERT_WEBHOOK_SECRET' => 's3cret')) }

    it 'accepts the X-Alert-Secret header' do
      request.headers['X-Alert-Secret'] = 's3cret'

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(1)
    end

    it 'accepts a bearer token' do
      request.headers['Authorization'] = 'Bearer s3cret'

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:ok)
      expect(Incident.count).to eq(1)
    end

    it 'rejects a wrong secret' do
      request.headers['X-Alert-Secret'] = 'nope'

      post :ingest, params: { alerts: [firing_alert] }

      expect(response).to have_http_status(:unauthorized)
      expect(Incident.count).to eq(0)
    end
  end
end
