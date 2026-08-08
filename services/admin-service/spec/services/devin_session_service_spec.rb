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
    stub_const('ENV', ENV.to_h.except('DEVIN_API_KEY', 'DEVIN_ORG_ID'))
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
end
