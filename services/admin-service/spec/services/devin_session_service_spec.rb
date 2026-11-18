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
end

RSpec.describe DevinSessionService, 'HTTP paths' do
  let(:incident) { create(:incident, title: 'Uploads failing', severity: 'critical', description: 'S3 PutObject 500') }

  before do
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('DEVIN_API_KEY', nil).and_return('env-key')
    allow(ENV).to receive(:fetch).with('DEVIN_ORG_ID', nil).and_return('org-env')
    allow(AdminSettingsService).to receive(:devin_credentials).and_return({ api_key: nil, org_id: nil })
    allow(Rails.logger).to receive(:error)
  end

  def http_response(klass, code, body)
    klass.new('1.1', code, 'msg').tap { |r| allow(r).to receive(:body).and_return(body) }
  end

  describe '.create_session' do
    it 'posts the incident prompt to the v3 sessions endpoint with env credentials' do
      http = instance_double(Net::HTTP)
      captured = nil
      allow(Net::HTTP).to receive(:new).with('api.devin.ai', 443).and_return(http)
      allow(http).to receive(:use_ssl=)
      allow(http).to receive(:open_timeout=)
      allow(http).to receive(:read_timeout=)
      allow(http).to receive(:request) do |req|
        captured = req
        http_response(Net::HTTPOK, '200', { session_id: 'devin-1', url: 'https://app.devin.ai/sessions/devin-1' }.to_json)
      end

      result = described_class.create_session(incident: incident)

      expect(result).to eq({ session_id: 'devin-1', url: 'https://app.devin.ai/sessions/devin-1' })
      expect(http).to have_received(:use_ssl=).with(true)
      expect(captured.path).to eq('/v3/organizations/org-env/sessions')
      expect(captured['Authorization']).to eq('Bearer env-key')
      prompt = JSON.parse(captured.body)['prompt']
      expect(prompt).to include('**Title**: Uploads failing', '**Severity**: critical',
                                '**Affected Service**: file-service', '**Description**: S3 PutObject 500')
    end

    it 'labels a missing affected service as Unknown' do
      incident.update!(affected_service: nil)
      captured = nil
      allow(described_class).to receive(:make_request) do |_uri, req|
        captured = req
        nil
      end

      described_class.create_session(incident: incident)
      expect(JSON.parse(captured.body)['prompt']).to include('**Affected Service**: Unknown')
    end

    it 'returns nil on a non-2xx response' do
      http = instance_double(Net::HTTP, :use_ssl= => nil, :open_timeout= => nil, :read_timeout= => nil)
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:request).and_return(http_response(Net::HTTPUnauthorized, '401', 'bad key'))

      expect(described_class.create_session(incident: incident)).to be_nil
      expect(Rails.logger).to have_received(:error).with('Devin API returned 401: bad key')
    end

    it 'returns nil and logs when the request raises' do
      allow(described_class).to receive(:make_request).and_raise(Net::OpenTimeout, 'timed out')
      expect(described_class.create_session(incident: incident)).to be_nil
      expect(Rails.logger).to have_received(:error).with(/Devin session creation failed: timed out/)
    end

    it 'returns nil when the response body is not JSON' do
      allow(described_class).to receive(:make_request).and_return(instance_double(Net::HTTPOK, body: '<html>'))
      expect(described_class.create_session(incident: incident)).to be_nil
    end
  end

  describe '.get_session' do
    it 'returns status and url' do
      captured = nil
      allow(described_class).to receive(:make_request) do |uri, req|
        captured = [uri, req]
        instance_double(Net::HTTPOK, body: { status: 'running', url: 'https://app.devin.ai/sessions/s1' }.to_json)
      end

      expect(described_class.get_session(session_id: 's1')).to eq({ status: 'running', url: 'https://app.devin.ai/sessions/s1' })
      expect(captured[0].path).to eq('/v3/organizations/org-env/sessions/s1')
      expect(captured[1]).to be_a(Net::HTTP::Get)
      expect(captured[1]['Authorization']).to eq('Bearer env-key')
    end

    it 'falls back to status_enum' do
      allow(described_class).to receive(:make_request)
        .and_return(instance_double(Net::HTTPOK, body: { status_enum: 'blocked' }.to_json))
      expect(described_class.get_session(session_id: 's1')).to eq({ status: 'blocked', url: nil })
    end

    it 'returns nil without a session id' do
      expect(described_class.get_session(session_id: nil)).to be_nil
    end

    it 'returns nil without credentials' do
      allow(ENV).to receive(:fetch).with('DEVIN_API_KEY', nil).and_return(nil)
      expect(described_class.get_session(session_id: 's1')).to be_nil
    end

    it 'returns nil when the API call fails' do
      allow(described_class).to receive(:make_request).and_return(nil)
      expect(described_class.get_session(session_id: 's1')).to be_nil
    end

    it 'returns nil and logs on exceptions' do
      allow(described_class).to receive(:make_request).and_raise(SocketError, 'dns')
      expect(described_class.get_session(session_id: 's1')).to be_nil
      expect(Rails.logger).to have_received(:error).with(/status fetch failed: dns/)
    end
  end

  describe '.credentials_status' do
    it 'reports env credentials as configured' do
      expect(described_class.credentials_status).to eq({ api_key_configured: true, org_id_configured: true })
    end

    it 'reports missing credentials' do
      allow(ENV).to receive(:fetch).with('DEVIN_API_KEY', nil).and_return(nil)
      allow(ENV).to receive(:fetch).with('DEVIN_ORG_ID', nil).and_return(nil)
      expect(described_class.credentials_status).to eq({ api_key_configured: false, org_id_configured: false })
    end
  end
end
