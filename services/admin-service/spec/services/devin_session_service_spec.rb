require 'rails_helper'

RSpec.describe DevinSessionService do
  let(:incident) { build(:incident, title: 'Search 500s', severity: 'critical', affected_service: 'search-service') }
  let(:http) do
    instance_double(Net::HTTP, :use_ssl= => nil, :open_timeout= => nil, :read_timeout= => nil)
  end

  def response_for(klass, code, body)
    response = klass.new('1.1', code, 'message')
    allow(response).to receive(:body).and_return(body)
    response
  end

  def with_credentials(&block)
    with_env('DEVIN_API_KEY' => 'key-123', 'DEVIN_ORG_ID' => 'org-456', &block)
  end

  # Records the Net::HTTP request object the service builds so it can be asserted on.
  def capture_request(body = '{}')
    captured = {}
    allow(http).to receive(:request) do |request|
      captured[:value] = request
      response_for(Net::HTTPOK, '200', body)
    end
    captured
  end

  before { allow(Net::HTTP).to receive(:new).and_return(http) }

  describe '.create_session' do
    it 'returns nil and warns when the credentials are missing' do
      allow(Rails.logger).to receive(:warn)

      result = with_env('DEVIN_API_KEY' => nil, 'DEVIN_ORG_ID' => nil) do
        described_class.create_session(incident: incident)
      end

      expect(result).to be_nil
      expect(Rails.logger).to have_received(:warn).with(/skipping Devin session creation/)
      expect(Net::HTTP).not_to have_received(:new)
    end

    it 'posts the incident prompt and returns the session id and url' do
      body = { 'session_id' => 'devin-1', 'url' => 'https://app.devin.ai/sessions/devin-1' }.to_json
      allow(http).to receive(:request).and_return(response_for(Net::HTTPOK, '200', body))

      result = with_credentials { described_class.create_session(incident: incident) }

      expect(result).to eq(session_id: 'devin-1', url: 'https://app.devin.ai/sessions/devin-1')
      expect(Net::HTTP).to have_received(:new).with('api.devin.ai', 443)
    end

    it 'sends the auth header and a prompt describing the incident' do
      request = capture_request

      with_credentials { described_class.create_session(incident: incident) }

      expect(request[:value]['Authorization']).to eq('Bearer key-123')
      expect(request[:value]['Content-Type']).to eq('application/json')
      prompt = JSON.parse(request[:value].body)['prompt']
      expect(prompt).to include('Search 500s', 'critical', 'search-service')
    end

    it 'describes an unknown affected service when the incident has none' do
      request = capture_request
      incident.affected_service = nil

      with_credentials { described_class.create_session(incident: incident) }

      expect(JSON.parse(request[:value].body)['prompt']).to include('**Affected Service**: Unknown')
    end

    it 'returns nil and logs when the API responds with an error status' do
      allow(Rails.logger).to receive(:error)
      allow(http).to receive(:request).and_return(response_for(Net::HTTPInternalServerError, '500', 'boom'))

      result = with_credentials { described_class.create_session(incident: incident) }

      expect(result).to be_nil
      expect(Rails.logger).to have_received(:error).with('Devin API returned 500: boom')
    end

    it 'returns nil and logs when the request raises' do
      allow(Rails.logger).to receive(:error)
      allow(http).to receive(:request).and_raise(Net::OpenTimeout, 'timed out')

      result = with_credentials { described_class.create_session(incident: incident) }

      expect(result).to be_nil
      expect(Rails.logger).to have_received(:error).with(/Devin session creation failed/)
    end
  end

  describe '.get_session' do
    it 'returns nil when the session id is missing' do
      result = with_credentials { described_class.get_session(session_id: nil) }

      expect(result).to be_nil
      expect(Net::HTTP).not_to have_received(:new)
    end

    it 'returns nil when the credentials are missing' do
      result = with_env('DEVIN_API_KEY' => nil, 'DEVIN_ORG_ID' => nil) do
        described_class.get_session(session_id: 'devin-1')
      end

      expect(result).to be_nil
    end

    it 'returns the status and url' do
      body = { 'status' => 'running', 'url' => 'https://app.devin.ai/sessions/devin-1' }.to_json
      allow(http).to receive(:request).and_return(response_for(Net::HTTPOK, '200', body))

      result = with_credentials { described_class.get_session(session_id: 'devin-1') }

      expect(result).to eq(status: 'running', url: 'https://app.devin.ai/sessions/devin-1')
    end

    it 'falls back to status_enum when status is absent' do
      body = { 'status_enum' => 'blocked', 'url' => nil }.to_json
      allow(http).to receive(:request).and_return(response_for(Net::HTTPOK, '200', body))

      result = with_credentials { described_class.get_session(session_id: 'devin-1') }

      expect(result[:status]).to eq('blocked')
    end

    it 'returns nil when the API errors' do
      allow(Rails.logger).to receive(:error)
      allow(http).to receive(:request).and_return(response_for(Net::HTTPNotFound, '404', 'missing'))

      expect(with_credentials { described_class.get_session(session_id: 'devin-1') }).to be_nil
    end

    it 'returns nil and logs when the response body is not JSON' do
      allow(Rails.logger).to receive(:error)
      allow(http).to receive(:request).and_return(response_for(Net::HTTPOK, '200', 'not json'))

      result = with_credentials { described_class.get_session(session_id: 'devin-1') }

      expect(result).to be_nil
      expect(Rails.logger).to have_received(:error).with(/Devin session status fetch failed/)
    end
  end
end
