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

  it 'treats a success without a session id as no session' do
    allow(AdminSettingsService).to receive(:devin_credentials)
      .and_return({ api_key: 'stored-key', org_id: 'org-123' })
    allow(described_class).to receive(:make_request)
      .and_return(instance_double(Net::HTTPOK, body: { url: 'https://app.devin.ai/x' }.to_json))

    expect(described_class.create_session(incident: incident)).to be_nil
  end

  describe '.credentials_status' do
    it 'answers explicitly when verification is asked for without credentials' do
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: nil, org_id: nil })

      status = described_class.credentials_status(verify: true)
      expect(status).to include(source: 'none', valid: false, error: 'Credentials not configured')
    end

    it 'flags a pair the Devin API rejects' do
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: 'stored-key', org_id: 'org-123' })
      allow(described_class).to receive(:raw_request)
        .and_return(instance_double(Net::HTTPForbidden, code: '403'))

      status = described_class.credentials_status(verify: true)
      expect(status).to include(source: 'settings', valid: false, error: 'Devin API returned 403')
    end

    it 'treats a Devin-side 503 as unreachable rather than a bad key' do
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: 'stored-key', org_id: 'org-123' })
      allow(described_class).to receive(:raw_request)
        .and_return(instance_double(Net::HTTPServiceUnavailable, code: '503'))

      expect(described_class.credentials_status(verify: true)).to include(valid: false, unreachable: true)
    end

    it 'treats a rate limit as unreachable rather than a bad key' do
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: 'stored-key', org_id: 'org-123' })
      allow(described_class).to receive(:raw_request)
        .and_return(instance_double(Net::HTTPTooManyRequests, code: '429'))

      expect(described_class.credentials_status(verify: true)).to include(valid: false, unreachable: true)
    end

    it 'marks a transport failure as unreachable rather than invalid credentials' do
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: 'stored-key', org_id: 'org-123' })
      allow(described_class).to receive(:raw_request).and_raise(Errno::ECONNREFUSED)

      expect(described_class.credentials_status(verify: true)).to include(valid: false, unreachable: true)
    end
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
end
