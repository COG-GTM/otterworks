require 'rails_helper'

RSpec.describe DevinSessionService do
  let(:incident) do
    build(:incident, title: 'Uploads failing', severity: 'critical', affected_service: 'file-service',
                     description: 'S3 puts return 500')
  end
  let(:http) do
    instance_double(Net::HTTP, :use_ssl= => nil, :open_timeout= => nil, :read_timeout= => nil)
  end

  def http_response(klass, code, body)
    response = klass.new('1.1', code, 'msg')
    allow(response).to receive(:body).and_return(body)
    response
  end

  def with_credentials(api_key: 'key-123', org_id: 'org-abc')
    stub_const('ENV', ENV.to_hash.merge('DEVIN_API_KEY' => api_key, 'DEVIN_ORG_ID' => org_id).compact)
  end

  before { allow(Net::HTTP).to receive(:new).and_return(http) }

  describe '.create_session' do
    it 'posts the incident prompt and returns the session id and url' do
      with_credentials
      body = { 'session_id' => 'devin-1', 'url' => 'https://app.devin.ai/sessions/devin-1' }.to_json
      allow(http).to receive(:request) { |req| @request = req }.and_return(http_response(Net::HTTPOK, '200', body))

      result = described_class.create_session(incident: incident)

      expect(result).to eq(session_id: 'devin-1', url: 'https://app.devin.ai/sessions/devin-1')
      expect(@request.path).to eq('/v3/organizations/org-abc/sessions')
      expect(@request['Authorization']).to eq('Bearer key-123')
      expect(JSON.parse(@request.body)['prompt']).to include('Uploads failing', 'critical', 'file-service',
                                                             'S3 puts return 500')
    end

    it 'falls back to Unknown for a blank affected service' do
      with_credentials
      allow(http).to receive(:request) { |req| @request = req }
        .and_return(http_response(Net::HTTPOK, '200', '{}'))

      described_class.create_session(incident: build(:incident, affected_service: nil))

      expect(JSON.parse(@request.body)['prompt']).to include('**Affected Service**: Unknown')
    end

    it 'returns nil and warns when credentials are missing' do
      with_credentials(api_key: nil)
      allow(Rails.logger).to receive(:warn)

      expect(described_class.create_session(incident: incident)).to be_nil
      expect(Rails.logger).to have_received(:warn).with(/not set/)
      expect(Net::HTTP).not_to have_received(:new)
    end

    it 'returns nil and logs when the API responds with an error' do
      with_credentials
      allow(http).to receive(:request).and_return(http_response(Net::HTTPBadRequest, '400', 'nope'))
      allow(Rails.logger).to receive(:error)

      expect(described_class.create_session(incident: incident)).to be_nil
      expect(Rails.logger).to have_received(:error).with('Devin API returned 400: nope')
    end

    it 'returns nil and logs when the request raises' do
      with_credentials
      allow(http).to receive(:request).and_raise(Net::OpenTimeout, 'timed out')
      allow(Rails.logger).to receive(:error)

      expect(described_class.create_session(incident: incident)).to be_nil
      expect(Rails.logger).to have_received(:error).with(/Devin session creation failed/)
    end
  end

  describe '.get_session' do
    it 'returns the status and url of the session' do
      with_credentials
      body = { 'status' => 'running', 'url' => 'https://app.devin.ai/sessions/devin-1' }.to_json
      allow(http).to receive(:request) { |req| @request = req }.and_return(http_response(Net::HTTPOK, '200', body))

      result = described_class.get_session(session_id: 'devin-1')

      expect(result).to eq(status: 'running', url: 'https://app.devin.ai/sessions/devin-1')
      expect(@request.path).to eq('/v3/organizations/org-abc/sessions/devin-1')
      expect(@request['Authorization']).to eq('Bearer key-123')
    end

    it 'falls back to status_enum when status is absent' do
      with_credentials
      body = { 'status_enum' => 'finished' }.to_json
      allow(http).to receive(:request).and_return(http_response(Net::HTTPOK, '200', body))

      expect(described_class.get_session(session_id: 'devin-1')[:status]).to eq('finished')
    end

    it 'returns nil when the session id is missing' do
      with_credentials

      expect(described_class.get_session(session_id: nil)).to be_nil
      expect(Net::HTTP).not_to have_received(:new)
    end

    it 'returns nil when the API responds with an error' do
      with_credentials
      allow(http).to receive(:request).and_return(http_response(Net::HTTPNotFound, '404', 'missing'))
      allow(Rails.logger).to receive(:error)

      expect(described_class.get_session(session_id: 'devin-1')).to be_nil
    end

    it 'returns nil and logs when the response body is not JSON' do
      with_credentials
      allow(http).to receive(:request).and_return(http_response(Net::HTTPOK, '200', 'not-json'))
      allow(Rails.logger).to receive(:error)

      expect(described_class.get_session(session_id: 'devin-1')).to be_nil
      expect(Rails.logger).to have_received(:error).with(/Devin session status fetch failed/)
    end
  end
end
