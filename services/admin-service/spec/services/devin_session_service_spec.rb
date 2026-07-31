require 'rails_helper'

RSpec.describe DevinSessionService do
  let(:incident) { build(:incident, title: 'Search 500s', severity: 'critical', affected_service: 'search-service') }
  let(:http) do
    instance_double(Net::HTTP, :use_ssl= => nil, :open_timeout= => nil, :read_timeout= => nil)
  end

  def success_response(body)
    response = Net::HTTPOK.new('1.1', '200', 'OK')
    allow(response).to receive(:body).and_return(body)
    response
  end

  def error_response(code, body)
    response = Net::HTTPInternalServerError.new('1.1', code, 'Error')
    allow(response).to receive(:body).and_return(body)
    response
  end

  def stub_credentials(api_key: 'devin-key', org_id: 'org-123')
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('DEVIN_API_KEY', nil).and_return(api_key)
    allow(ENV).to receive(:fetch).with('DEVIN_ORG_ID', nil).and_return(org_id)
  end

  describe '.create_session' do
    it 'posts an incident prompt and returns the session id and url' do
      stub_credentials
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:request) do |request|
        expect(request['Authorization']).to eq('Bearer devin-key')
        expect(request['Content-Type']).to eq('application/json')
        expect(JSON.parse(request.body)['prompt']).to include('Search 500s', 'critical', 'search-service')
        success_response({ session_id: 'devin-1', url: 'https://app.devin.ai/sessions/1' }.to_json)
      end

      expect(described_class.create_session(incident: incident))
        .to eq(session_id: 'devin-1', url: 'https://app.devin.ai/sessions/1')
      expect(Net::HTTP).to have_received(:new).with('api.devin.ai', 443)
    end

    it 'falls back to "Unknown" for an incident without an affected service' do
      stub_credentials
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:request) do |request|
        expect(JSON.parse(request.body)['prompt']).to include('**Affected Service**: Unknown')
        success_response({ session_id: 's', url: 'u' }.to_json)
      end

      described_class.create_session(incident: build(:incident, affected_service: nil))
    end

    it 'returns nil and warns when credentials are missing' do
      stub_credentials(api_key: nil)
      allow(Rails.logger).to receive(:warn)

      expect(described_class.create_session(incident: incident)).to be_nil
      expect(Rails.logger).to have_received(:warn).with(/DEVIN_API_KEY or DEVIN_ORG_ID not set/)
    end

    it 'returns nil when the API responds with an error status' do
      stub_credentials
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:request).and_return(error_response('500', 'upstream boom'))
      allow(Rails.logger).to receive(:error)

      expect(described_class.create_session(incident: incident)).to be_nil
      expect(Rails.logger).to have_received(:error).with('Devin API returned 500: upstream boom')
    end

    it 'returns nil and logs when the request raises' do
      stub_credentials
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:request).and_raise(Net::OpenTimeout, 'timed out')
      allow(Rails.logger).to receive(:error)

      expect(described_class.create_session(incident: incident)).to be_nil
      expect(Rails.logger).to have_received(:error).with(/Devin session creation failed/)
    end
  end

  describe '.get_session' do
    it 'returns the session status and url' do
      stub_credentials
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:request) do |request|
        expect(request.path).to eq('/v3/organizations/org-123/sessions/devin-1')
        expect(request['Authorization']).to eq('Bearer devin-key')
        success_response({ status: 'running', url: 'https://app.devin.ai/sessions/1' }.to_json)
      end

      expect(described_class.get_session(session_id: 'devin-1'))
        .to eq(status: 'running', url: 'https://app.devin.ai/sessions/1')
    end

    it 'falls back to status_enum when status is absent' do
      stub_credentials
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:request).and_return(success_response({ status_enum: 'blocked' }.to_json))

      expect(described_class.get_session(session_id: 'devin-1')).to eq(status: 'blocked', url: nil)
    end

    it 'returns nil without a session id' do
      stub_credentials

      expect(described_class.get_session(session_id: nil)).to be_nil
    end

    it 'returns nil when credentials are missing' do
      stub_credentials(org_id: nil)

      expect(described_class.get_session(session_id: 'devin-1')).to be_nil
    end

    it 'returns nil when the API errors' do
      stub_credentials
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:request).and_return(error_response('404', 'not found'))
      allow(Rails.logger).to receive(:error)

      expect(described_class.get_session(session_id: 'missing')).to be_nil
    end

    it 'returns nil and logs when the response body is not JSON' do
      stub_credentials
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:request).and_return(success_response('<html>nope</html>'))
      allow(Rails.logger).to receive(:error)

      expect(described_class.get_session(session_id: 'devin-1')).to be_nil
      expect(Rails.logger).to have_received(:error).with(/Devin session status fetch failed/)
    end
  end
end
