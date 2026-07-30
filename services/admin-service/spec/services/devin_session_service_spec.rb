require 'rails_helper'

RSpec.describe DevinSessionService do
  let(:incident) { build(:incident, title: 'Search 500s', severity: 'critical', affected_service: 'search-service') }
  let(:http) { instance_double(Net::HTTP) }

  before do
    allow(http).to receive(:use_ssl=)
    allow(http).to receive(:open_timeout=)
    allow(http).to receive(:read_timeout=)
    allow(Net::HTTP).to receive(:new).and_return(http)
    stub_const('ENV', ENV.to_hash.merge('DEVIN_API_KEY' => 'key-123', 'DEVIN_ORG_ID' => 'org-abc'))
  end

  def http_response(klass, code, body)
    response = klass.new('1.1', code, 'OK')
    allow(response).to receive(:body).and_return(body)
    response
  end

  def stub_http(klass, body)
    allow(http).to receive(:request).and_return(http_response(klass, '200', body))
  end

  describe '.create_session' do
    it 'posts the incident prompt and returns the session handle' do
      stub_http(Net::HTTPOK, { 'session_id' => 'sess-1', 'url' => 'https://app.devin.ai/sessions/1' }.to_json)

      result = described_class.create_session(incident: incident)

      expect(result).to eq(session_id: 'sess-1', url: 'https://app.devin.ai/sessions/1')
      expect(http).to have_received(:request) do |request|
        expect(request['Authorization']).to eq('Bearer key-123')
        expect(request['Content-Type']).to eq('application/json')
        expect(JSON.parse(request.body)['prompt']).to include('Search 500s', 'search-service', 'critical')
      end
    end

    it 'falls back to Unknown for a blank affected service' do
      stub_http(Net::HTTPOK, {}.to_json)
      incident.affected_service = nil

      described_class.create_session(incident: incident)

      expect(http).to have_received(:request) do |request|
        expect(JSON.parse(request.body)['prompt']).to include('**Affected Service**: Unknown')
      end
    end

    it 'returns nil when the API credentials are missing' do
      stub_const('ENV', ENV.to_hash.except('DEVIN_API_KEY'))
      allow(Rails.logger).to receive(:warn)

      expect(described_class.create_session(incident: incident)).to be_nil
      expect(Rails.logger).to have_received(:warn).with(/not set/)
      expect(Net::HTTP).not_to have_received(:new)
    end

    it 'returns nil and logs when the API responds with an error' do
      allow(http).to receive(:request).and_return(http_response(Net::HTTPBadRequest, '400', 'bad request'))
      allow(Rails.logger).to receive(:error)

      expect(described_class.create_session(incident: incident)).to be_nil
      expect(Rails.logger).to have_received(:error).with(/400/)
    end

    it 'returns nil and logs when the request raises' do
      allow(http).to receive(:request).and_raise(Errno::ECONNREFUSED, 'refused')
      allow(Rails.logger).to receive(:error)

      expect(described_class.create_session(incident: incident)).to be_nil
      expect(Rails.logger).to have_received(:error).with(/refused/)
    end
  end

  describe '.get_session' do
    it 'returns the session status and url' do
      stub_http(Net::HTTPOK, { 'status' => 'running', 'url' => 'https://app.devin.ai/sessions/1' }.to_json)

      expect(described_class.get_session(session_id: 'sess-1'))
        .to eq(status: 'running', url: 'https://app.devin.ai/sessions/1')
    end

    it 'falls back to status_enum' do
      stub_http(Net::HTTPOK, { 'status_enum' => 'finished' }.to_json)

      expect(described_class.get_session(session_id: 'sess-1')[:status]).to eq('finished')
    end

    it 'returns nil without a session id' do
      expect(described_class.get_session(session_id: nil)).to be_nil
      expect(Net::HTTP).not_to have_received(:new)
    end

    it 'returns nil when credentials are missing' do
      stub_const('ENV', ENV.to_hash.except('DEVIN_ORG_ID'))

      expect(described_class.get_session(session_id: 'sess-1')).to be_nil
    end

    it 'returns nil when the API responds with an error' do
      allow(http).to receive(:request).and_return(http_response(Net::HTTPNotFound, '404', 'missing'))
      allow(Rails.logger).to receive(:error)

      expect(described_class.get_session(session_id: 'sess-1')).to be_nil
      expect(Rails.logger).to have_received(:error).with(/404/)
    end

    it 'returns nil and logs when the body is not JSON' do
      stub_http(Net::HTTPOK, 'not json')
      allow(Rails.logger).to receive(:error)

      expect(described_class.get_session(session_id: 'sess-1')).to be_nil
      expect(Rails.logger).to have_received(:error).with(/status fetch failed/)
    end
  end
end
