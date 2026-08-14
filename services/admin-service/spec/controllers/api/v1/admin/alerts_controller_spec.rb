require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  # The webhook is unauthenticated only when the secret is unset; pin it so the
  # suite behaves the same inside the docker-compose container, which sets one.
  around { |example| with_env('ALERT_WEBHOOK_SECRET' => nil) { example.run } }

  before do
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
  end

  def firing_alert(overrides = {})
    {
      status: 'firing',
      labels: { alertname: 'SearchSuggest5xx', severity: 'critical', affected_service: 'search-service' },
      annotations: { summary: 'Search suggest is failing', description: 'Error rate above 5%' }
    }.deep_merge(overrides)
  end

  describe 'POST #ingest' do
    it 'rejects a payload without an alerts array' do
      post :ingest, params: { receiver: 'otterworks-webhook' }

      expect(response).to have_http_status(:bad_request)
      expect(JSON.parse(response.body)['error']).to eq('Missing alerts array')
    end

    it 'creates an investigating incident from a firing alert' do
      expect { post :ingest, params: { alerts: [firing_alert] } }.to change(Incident, :count).by(1)

      expect(response).to have_http_status(:ok)
      incident = Incident.last
      expect(incident).to have_attributes(title: 'Search suggest is failing', severity: 'critical',
                                          status: 'investigating', affected_service: 'search-service',
                                          reporter_id: nil)
      expect(incident.description).to include('Error rate above 5%', '**Alert**: SearchSuggest5xx',
                                              '**Source**: Grafana Unified Alerting')
      body = JSON.parse(response.body)
      expect(body).to include('received' => 1, 'processed' => 1)
      expect(body['incidents'].first).to include('incident_id' => incident.id, 'devin_session' => false)
    end

    it 'attaches a Devin session when one is created' do
      allow(DevinSessionService).to receive(:create_session)
        .and_return({ session_id: 'devin-3', url: 'https://app.devin.ai/sessions/devin-3' })

      post :ingest, params: { alerts: [firing_alert] }

      expect(Incident.last).to have_attributes(devin_session_id: 'devin-3', devin_session_status: 'running')
      expect(JSON.parse(response.body)['incidents'].first['devin_session']).to be(true)
    end

    it 'leaves the incident open and skips Devin when auto-investigate is disabled' do
      allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(false)

      post :ingest, params: { alerts: [firing_alert] }

      expect(Incident.last.status).to eq('open')
      expect(DevinSessionService).not_to have_received(:create_session)
    end

    it 'maps grafana severities onto incident severities' do
      post :ingest, params: { alerts: [firing_alert(labels: { severity: 'warning' })] }

      expect(Incident.last.severity).to eq('medium')
    end

    it 'defaults an unknown severity to medium' do
      post :ingest, params: { alerts: [firing_alert(labels: { severity: 'spicy' })] }

      expect(Incident.last.severity).to eq('medium')
    end

    it 'falls back to the service label and a generated title' do
      alert = { status: 'firing', labels: { alertname: 'DocsSlow', severity: 'high', service: 'document-service' },
                annotations: {} }

      post :ingest, params: { alerts: [alert] }

      expect(Incident.last).to have_attributes(affected_service: 'document-service', severity: 'high',
                                               title: 'DocsSlow: document-service alert firing')
    end

    it 'includes the runbook link when the alert carries one' do
      alert = firing_alert(annotations: { runbook_url: 'https://runbooks.otterworks.test/search' })

      post :ingest, params: { alerts: [alert] }

      expect(Incident.last.description).to include('**Runbook**: https://runbooks.otterworks.test/search')
    end

    it 'omits the alert name from the description when the label is missing' do
      alert = { status: 'firing', labels: { severity: 'high', affected_service: 'audit-service' },
                annotations: { summary: 'Audit lag' } }

      post :ingest, params: { alerts: [alert] }

      expect(Incident.last.description).not_to include('**Alert**')
      expect(Incident.last.description).to include('Audit lag', '**Source**: Grafana Unified Alerting')
    end

    it 'ignores an alert with no affected service' do
      alert = { status: 'firing', labels: { alertname: 'Nameless', severity: 'high' }, annotations: {} }

      expect { post :ingest, params: { alerts: [alert] } }.not_to change(Incident, :count)

      expect(JSON.parse(response.body)).to include('received' => 1, 'processed' => 0)
    end

    it 'ignores an alert in an unknown state' do
      expect { post :ingest, params: { alerts: [firing_alert(status: 'pending')] } }
        .not_to change(Incident, :count)
    end

    it 'deduplicates against an already-open incident for the service' do
      existing = create(:incident, :investigating, affected_service: 'search-service')

      expect { post :ingest, params: { alerts: [firing_alert] } }.not_to change(Incident, :count)

      expect(JSON.parse(response.body)['incidents'].first)
        .to include('skipped' => true, 'incident_id' => existing.id, 'reason' => 'duplicate')
    end

    it 'logs and skips an alert whose incident fails validation' do
      allow(Rails.logger).to receive(:error)
      allow(Incident).to receive(:create!).and_raise(ActiveRecord::RecordInvalid.new(Incident.new))

      post :ingest, params: { alerts: [firing_alert] }

      expect(JSON.parse(response.body)).to include('received' => 1, 'processed' => 0)
      expect(Rails.logger).to have_received(:error).with(/Failed to create incident from alert SearchSuggest5xx/)
    end

    it 'auto-resolves the open incident when the alert resolves' do
      incident = create(:incident, :investigating, affected_service: 'search-service')

      post :ingest, params: { alerts: [firing_alert(status: 'resolved')] }

      expect(incident.reload.status).to eq('resolved')
      expect(JSON.parse(response.body)).to include('processed' => 0)
    end

    it 'ignores a resolved alert with no matching open incident' do
      expect { post :ingest, params: { alerts: [firing_alert(status: 'resolved')] } }
        .not_to change(Incident, :count)

      expect(response).to have_http_status(:ok)
    end

    it 'ignores a resolved alert with no affected service' do
      alert = { status: 'resolved', labels: { alertname: 'Nameless' }, annotations: {} }

      post :ingest, params: { alerts: [alert] }

      expect(response).to have_http_status(:ok)
    end

    it 'warns when the matching incident cannot be resolved' do
      incident = create(:incident, :investigating, affected_service: 'search-service')
      allow(Rails.logger).to receive(:warn)
      stub_const('Incident::VALID_TRANSITIONS', { 'investigating' => [] })

      post :ingest, params: { alerts: [firing_alert(status: 'resolved')] }

      expect(Rails.logger).to have_received(:warn).with(/Could not auto-resolve incident #{incident.id}/)
    end
  end

  describe 'webhook authentication' do
    it 'allows the request when no secret is configured' do
      with_env('ALERT_WEBHOOK_SECRET' => nil) do
        post :ingest, params: { alerts: [firing_alert] }
      end

      expect(response).to have_http_status(:ok)
    end

    it 'accepts the X-Alert-Secret header' do
      request.headers['X-Alert-Secret'] = 'sekret'

      with_env('ALERT_WEBHOOK_SECRET' => 'sekret') do
        post :ingest, params: { alerts: [firing_alert] }
      end

      expect(response).to have_http_status(:ok)
    end

    it 'accepts a bearer token' do
      request.headers['Authorization'] = 'Bearer sekret'

      with_env('ALERT_WEBHOOK_SECRET' => 'sekret') do
        post :ingest, params: { alerts: [firing_alert] }
      end

      expect(response).to have_http_status(:ok)
    end

    it 'rejects a wrong secret' do
      request.headers['X-Alert-Secret'] = 'nope'

      with_env('ALERT_WEBHOOK_SECRET' => 'sekret') do
        post :ingest, params: { alerts: [firing_alert] }
      end

      expect(response).to have_http_status(:unauthorized)
      expect(JSON.parse(response.body)['error']).to eq('Unauthorized')
    end
  end
end
