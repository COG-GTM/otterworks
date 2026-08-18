require 'rails_helper'

RSpec.describe Api::V1::Admin::AlertsController do
  before do
    allow(AdminSettingsService).to receive(:auto_investigate_enabled?).and_return(true)
    allow(DevinSessionService).to receive(:create_session).and_return(nil)
    allow(DevinSessionService).to receive(:configured?).and_return(true)
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

    it 'marks the incident when the session could not be created' do
      post :ingest, params: { alerts: [firing_alert] }
      expect(Incident.last.devin_session_status).to eq('failed')
    end

    it 'leaves the status blank on a tenant with no Devin credentials' do
      allow(DevinSessionService).to receive(:configured?).and_return(false)

      post :ingest, params: { alerts: [firing_alert] }
      expect(Incident.last.devin_session_status).to be_nil
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

    it 'stops opening dedup=false incidents once the per-service ceiling is hit' do
      stub_const("#{described_class}::UNDEDUPED_LIMIT", 2)

      3.times do
        post :ingest, params: { alerts: [firing_alert(labels: { dedup: 'false' })] }
      end

      expect(Incident.count).to eq(2)
      expect(DevinSessionService).to have_received(:create_session).twice
      expect(response.parsed_body['incidents'].first['reason']).to eq('rate_limited')
    end

    it 'keeps the filename when it makes the summary too long' do
      # The client finds an upload's incident by the filename at the end of the
      # title, so shortening has to keep the whole tail.
      file_name = "#{'a' * 240}.txt"
      post :ingest, params: { alerts: [firing_alert(summary: "File upload failed: #{file_name}")] }

      expect(Incident.count).to eq(1)
      expect(Incident.last.title.length).to eq(255)
      expect(Incident.last.title).to end_with(": #{file_name}")
      expect(DevinSessionService).to have_received(:create_session).once
    end

    it 'still opens an incident when even the filename does not fit' do
      post :ingest, params: { alerts: [firing_alert(summary: "File upload failed: #{'a' * 400}.txt")] }

      expect(Incident.count).to eq(1)
      expect(Incident.last.title.length).to eq(255)
      expect(DevinSessionService).to have_received(:create_session).once
    end

    it 'rejects payloads without an alerts array' do
      post :ingest, params: { foo: 'bar' }
      expect(response).to have_http_status(:bad_request)
    end
  end
end
