require 'rails_helper'

RSpec.describe HealthChecker do
  let(:http) { instance_double(Net::HTTP, :open_timeout= => nil, :read_timeout= => nil) }
  let(:redis) { instance_double(Redis, close: nil) }

  def http_response(code)
    instance_double(Net::HTTPResponse, code: code)
  end

  describe '.check_service' do
    before { allow(Net::HTTP).to receive(:new).and_return(http) }

    it 'reports a healthy service with a latency measurement' do
      allow(http).to receive(:get).with('/health').and_return(http_response('200'))

      status = described_class.check_service('auth-service')

      expect(status.name).to eq('auth-service')
      expect(status.status).to eq('healthy')
      expect(status.latency_ms).to be_a(Float)
      expect(Net::HTTP).to have_received(:new).with('auth-service', 8081)
    end

    it 'honours the per-service host and port env vars' do
      allow(http).to receive(:get).and_return(http_response('200'))

      with_env('FILE_SERVICE_HOST' => 'files.internal', 'FILE_SERVICE_PORT' => '9999') do
        described_class.check_service('file-service')
      end

      expect(Net::HTTP).to have_received(:new).with('files.internal', 9999)
    end

    it 'reports unhealthy for a non-200 response' do
      allow(http).to receive(:get).and_return(http_response('503'))

      expect(described_class.check_service('search-service').status).to eq('unhealthy')
    end

    it 'reports unhealthy with the error message when the request raises' do
      allow(http).to receive(:get).and_raise(Errno::ECONNREFUSED, 'nope')

      status = described_class.check_service('audit-service')

      expect(status.status).to eq('unhealthy')
      expect(status.message).to match(/Connection refused/)
      expect(status.latency_ms).to be_a(Float)
    end

    it 'reports unknown when no port is configured for the service' do
      status = described_class.check_service('mystery-service')

      expect(status.status).to eq('unknown')
      expect(status.message).to eq('No endpoint configured')
      expect(Net::HTTP).not_to have_received(:new)
    end
  end

  describe '.check_database' do
    it 'reports healthy against the real connection' do
      result = described_class.check_database

      expect(result[:status]).to eq('healthy')
      expect(result[:latency_ms]).to be_a(Float)
    end

    it 'reports unhealthy when the query raises' do
      allow(ActiveRecord::Base).to receive(:connection).and_raise(ActiveRecord::StatementInvalid, 'no db')

      expect(described_class.check_database).to include(status: 'unhealthy', message: 'no db')
    end
  end

  describe '.check_redis' do
    before { allow(Redis).to receive(:new).and_return(redis) }

    it 'pings redis and closes the connection' do
      allow(redis).to receive(:ping).and_return('PONG')

      result = described_class.check_redis

      expect(result[:status]).to eq('healthy')
      expect(redis).to have_received(:close)
    end

    it 'builds the url from REDIS_HOST/REDIS_PORT when REDIS_URL is absent' do
      allow(redis).to receive(:ping)

      with_env('REDIS_URL' => nil, 'REDIS_HOST' => 'cache', 'REDIS_PORT' => '6390') do
        described_class.check_redis
      end

      expect(Redis).to have_received(:new).with(url: 'redis://cache:6390/0', timeout: 2)
    end

    it 'reports unhealthy when the connection cannot be built at all' do
      allow(Redis).to receive(:new).and_raise(Redis::CannotConnectError, 'no route')

      expect(described_class.check_redis).to include(status: 'unhealthy', message: 'no route')
    end

    it 'reports unhealthy when the ping raises' do
      allow(redis).to receive(:ping).and_raise(Redis::CannotConnectError, 'unreachable')

      expect(described_class.check_redis).to include(status: 'unhealthy', message: 'unreachable')
      expect(redis).to have_received(:close)
    end
  end

  describe '.check_all' do
    let(:healthy) do
      ->(name) { HealthChecker::ServiceStatus.new(name: name, status: 'healthy', latency_ms: 1.0) }
    end

    before do
      allow(described_class).to receive(:check_database).and_return({ status: 'healthy', latency_ms: 0.1 })
      allow(described_class).to receive(:check_redis).and_return({ status: 'healthy', latency_ms: 0.2 })
    end

    it 'is healthy when every service is healthy' do
      allow(described_class).to receive(:check_service) { |name| healthy.call(name) }

      result = described_class.check_all

      expect(result[:status]).to eq('healthy')
      expect(result[:services].size).to eq(described_class::SERVICES.size)
      expect(result[:services].first).to include(name: 'auth-service', status: 'healthy')
      expect(result[:database]).to include(status: 'healthy')
      expect(result[:redis]).to include(status: 'healthy')
      expect(result[:timestamp]).to be_present
    end

    it 'is degraded when any service is unhealthy' do
      unhealthy = lambda do |name|
        HealthChecker::ServiceStatus.new(name: name, status: 'unhealthy', latency_ms: 5.0)
      end
      allow(described_class).to receive(:check_service) do |name|
        name == 'file-service' ? unhealthy.call(name) : healthy.call(name)
      end

      expect(described_class.check_all[:status]).to eq('degraded')
    end
  end
end
