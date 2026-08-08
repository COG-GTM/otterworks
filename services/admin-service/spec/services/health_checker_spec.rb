require 'rails_helper'

RSpec.describe HealthChecker do
  let(:http) { instance_double(Net::HTTP) }
  let(:redis) { instance_double(Redis, close: nil) }

  before do
    allow(http).to receive(:open_timeout=)
    allow(http).to receive(:read_timeout=)
    allow(Net::HTTP).to receive(:new).and_return(http)
    allow(Redis).to receive(:new).and_return(redis)
    allow(redis).to receive(:ping).and_return('PONG')
  end

  def stub_response(code)
    allow(http).to receive(:get).and_return(instance_double(Net::HTTPResponse, code: code))
  end

  describe '.check_service' do
    it 'reports healthy when the service answers 200' do
      stub_response('200')

      status = described_class.check_service('auth-service')

      expect(status.name).to eq('auth-service')
      expect(status.status).to eq('healthy')
      expect(status.latency_ms).to be_a(Float)
    end

    it 'reports unhealthy on a non-200 response' do
      stub_response('503')

      expect(described_class.check_service('file-service').status).to eq('unhealthy')
    end

    it 'reports unhealthy with the error message when the request raises' do
      allow(http).to receive(:get).and_raise(Errno::ECONNREFUSED, 'nope')

      status = described_class.check_service('search-service')

      expect(status.status).to eq('unhealthy')
      expect(status.message).to match(/nope/)
    end

    it 'reports unknown when no port is configured' do
      stub_const('HealthChecker::DEFAULT_PORTS', {})
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('AUDIT_SERVICE_PORT', nil).and_return(nil)

      status = described_class.check_service('audit-service')

      expect(status.status).to eq('unknown')
      expect(status.message).to eq('No endpoint configured')
    end

    it 'honours host and port overrides from the environment' do
      stub_response('200')
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('AUTH_SERVICE_HOST', 'auth-service').and_return('auth.internal')
      allow(ENV).to receive(:fetch).with('AUTH_SERVICE_PORT', '8081').and_return('9999')

      described_class.check_service('auth-service')

      expect(Net::HTTP).to have_received(:new).with('auth.internal', 9999)
    end
  end

  describe '.check_database' do
    it 'reports healthy with a latency' do
      result = described_class.check_database

      expect(result[:status]).to eq('healthy')
      expect(result[:latency_ms]).to be_a(Float)
    end

    it 'reports unhealthy when the query raises' do
      allow(ActiveRecord::Base.connection).to receive(:execute).with('SELECT 1')
                                                               .and_raise(ActiveRecord::StatementInvalid, 'db gone')

      expect(described_class.check_database).to include(status: 'unhealthy', message: /db gone/)
    end
  end

  describe '.check_redis' do
    it 'pings redis and closes the connection' do
      result = described_class.check_redis

      expect(result[:status]).to eq('healthy')
      expect(redis).to have_received(:ping)
      expect(redis).to have_received(:close)
    end

    it 'reports unhealthy when the ping raises' do
      allow(redis).to receive(:ping).and_raise(Redis::CannotConnectError, 'redis down')

      expect(described_class.check_redis).to include(status: 'unhealthy', message: /redis down/)
    end
  end

  describe '.check_all' do
    it 'aggregates every service as healthy' do
      stub_response('200')

      result = described_class.check_all

      expect(result[:status]).to eq('healthy')
      expect(result[:services].map { |s| s[:name] }).to eq(described_class::SERVICES)
      expect(result[:database][:status]).to eq('healthy')
      expect(result[:redis][:status]).to eq('healthy')
      expect(result[:timestamp]).to be_present
    end

    it 'reports degraded when any service is unhealthy' do
      stub_response('500')

      expect(described_class.check_all[:status]).to eq('degraded')
    end
  end
end
