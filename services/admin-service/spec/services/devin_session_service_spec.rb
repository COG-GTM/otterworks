require 'rails_helper'

RSpec.describe DevinSessionService do
  let(:incident) do
    Incident.create!(
      title: 'File upload failed',
      description: 'boom',
      severity: 'critical',
      affected_service: 'file-service',
      status: 'open'
    )
  end

  before do
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('DEVIN_API_KEY', nil).and_return(nil)
    allow(ENV).to receive(:fetch).with('DEVIN_ORG_ID', nil).and_return(nil)
  end

  it 'skips session creation when no credentials are configured anywhere' do
    allow(AdminSettingsService).to receive(:devin_credentials)
      .and_return({ api_key: nil, org_id: nil })

    expect(described_class.create_session(incident: incident)).to be_nil
  end

  it 'falls back to settings-stored credentials when env vars are absent' do
    allow(AdminSettingsService).to receive(:devin_credentials)
      .and_return({ api_key: 'stored-key', org_id: 'org-123' })

    response = instance_double(Net::HTTPOK, body: { session_id: 's-1', url: 'https://app.devin.ai/s-1' }.to_json)
    captured_uri = nil
    allow(described_class).to receive(:make_request) do |uri, request|
      captured_uri = uri
      expect(request['Authorization']).to eq('Bearer stored-key')
      response
    end

    result = described_class.create_session(incident: incident)
    expect(captured_uri.to_s).to include('/organizations/org-123/sessions')
    expect(result).to eq({ session_id: 's-1', url: 'https://app.devin.ai/s-1' })
  end

  it 'does not pair an env api key with a stored org id' do
    allow(ENV).to receive(:fetch).with('DEVIN_API_KEY', nil).and_return('env-key')
    allow(AdminSettingsService).to receive(:devin_credentials)
      .and_return({ api_key: 'stored-key', org_id: 'org-123' })

    allow(described_class).to receive(:make_request) do |_uri, request|
      expect(request['Authorization']).to eq('Bearer stored-key')
      instance_double(Net::HTTPOK, body: { session_id: 's-1', url: 'u' }.to_json)
    end

    described_class.create_session(incident: incident)
  end

  describe 'the Slack alert the prompt opens with' do
    let(:upload_incident) do
      Incident.create!(
        title: 'File upload failed: q3-report.pdf',
        description: 'Upload of "q3-report.pdf" failed in file-service: StorageBackendError: bucket unavailable',
        severity: 'critical',
        affected_service: 'file-service',
        status: 'open',
        created_at: Time.utc(2026, 8, 17, 21, 50, 34)
      )
    end

    subject(:prompt) { described_class.send(:build_prompt, upload_incident) }

    it 'comes before anything else in the prompt' do
      expect(prompt).to start_with('## Step 0 — Post this alert to Slack IMMEDIATELY')
      expect(prompt).to include('#automated-alerts')
      expect(prompt.index('Step 0')).to be < prompt.index('## Incident Details')
    end

    it 'renders every field from the incident' do
      expect(prompt).to include(':rotating_light: Sentry Alert — OtterWorks — File Upload Error')
      expect(prompt).to include("Error:\nFile upload failed: q3-report.pdf")
      expect(prompt).to include("Severity:\ncritical")
      expect(prompt).to include("Location:\nservices/file-service/src/handlers.rs — upload_file")
      expect(prompt).to include("Type:\nStorageBackendError")
      expect(prompt).to include('Message: StorageBackendError: bucket unavailable')
      expect(prompt).to include('Service: file-service | 2026-08-17T21:50:34.000Z')
    end

    it 'lists both on-call entries and leaves the session URL to the session' do
      expect(prompt).to include(':robot_face: Devin AI (auto-investigating) — <DEVIN_SESSION_URL>')
      expect(prompt).to include('@golden demos')
    end

    it 'falls back for incidents from other services' do
      other = Incident.create!(
        title: 'Search degraded',
        description: 'MeiliSearch unreachable',
        severity: 'medium',
        affected_service: 'search-service',
        status: 'open'
      )

      other_prompt = described_class.send(:build_prompt, other)
      expect(other_prompt).to include('Sentry Alert — OtterWorks — Search Service Error')
      expect(other_prompt).to include("Location:\nservices/search-service")
      expect(other_prompt).to include("Type:\nServiceError")
      expect(other_prompt).to include('Message: MeiliSearch unreachable')
    end
  end
end
