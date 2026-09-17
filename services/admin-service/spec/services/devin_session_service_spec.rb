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

  it 'refuses session ids that are not opaque identifiers' do
    allow(AdminSettingsService).to receive(:devin_credentials)
      .and_return({ api_key: 'stored-key', org_id: 'org-123' })
    expect(described_class).not_to receive(:make_request)

    expect(described_class.get_session(session_id: '../../../v3/other')).to be_nil
  end

  it 'fetches a session for a well-formed id' do
    allow(AdminSettingsService).to receive(:devin_credentials)
      .and_return({ api_key: 'stored-key', org_id: 'org-123' })

    response = instance_double(Net::HTTPOK, body: { status: 'running', url: 'https://app.devin.ai/s-1' }.to_json)
    captured_uri = nil
    allow(described_class).to receive(:make_request) do |uri, _request|
      captured_uri = uri
      response
    end

    described_class.get_session(session_id: 's-1')
    expect(captured_uri.to_s).to eq('https://api.devin.ai/v3/organizations/org-123/sessions/s-1')
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
