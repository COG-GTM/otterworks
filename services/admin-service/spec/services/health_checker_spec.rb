require 'rails_helper'

RSpec.describe HealthChecker do
  let(:http) { instance_double(Net::HTTP, :open_timeout= => nil, :read_timeout= => nil) }

  describe '.check_service' do
    before { allow(Net::HTTP).to receive(:new).and_return(http) }

    it 'reports a healthy service when the endpoint answers 200' do
      allow(http).to receive(:get).with('/health').and_return(Net::HTTPOK.new('1.1', '200', 'OK'))

      status = described_class.check_service('auth-service')

      expect(Net::HTTP).to have_received(:new).with('auth-service', 8081)
      expect(status.name).to eq('auth-service')
      expect(status.status).to eq('healthy')
      expect(status.latency_ms).to be_a(Float)
    end

    it 'reports unhealthy when the endpoint answers a non-200' do
      allow(http).to receive(:get).and_return(Net::HTTPServiceUnavailable.new('1.1', '503', 'nope'))

      expect(described_class.check_service('file-service').status).to eq('unhealthy')
    end

    it 'honours host and port overrides from the environment' do
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('SEARCH_SERVICE_HOST', 'search-service').and_return('search.internal')
      allow(ENV).to receive(:fetch).with('SEARCH_SERVICE_PORT', '8087').and_return('9999')
      allow(http).to receive(:get).and_return(Net::HTTPOK.new('1.1', '200', 'OK'))

      described_class.check_service('search-service')

      expect(Net::HTTP).to have_received(:new).with('search.internal', 9999)
    end

    it 'reports unknown when no endpoint is configured' do
      status = described_class.check_service('mystery-service')

      expect(status.status).to eq('unknown')
      expect(status.message).to eq('No endpoint configured')
      expect(Net::HTTP).not_to have_received(:new)
    end

    it 'captures connection errors as unhealthy' do
      allow(http).to receive(:get).and_raise(Errno::ECONNREFUSED, 'connection refused')

      status = described_class.check_service('audit-service')

      expect(status.status).to eq('unhealthy')
      expect(status.message).to match(/connection refused/i)
    end
  end

  describe '.check_database' do
    it 'reports healthy with a latency measurement' do
      result = described_class.check_database

      expect(result[:status]).to eq('healthy')
      expect(result[:latency_ms]).to be_a(Float)
    end

    it 'reports unhealthy when the query blows up' do
      allow(ActiveRecord::Base).to receive(:connection).and_raise(ActiveRecord::ConnectionNotEstablished, 'no db')

      expect(described_class.check_database).to include(status: 'unhealthy', message: /no db/)
    end
  end

  describe '.check_redis' do
    let(:redis) { instance_double(Redis, close: nil) }

    before { allow(Redis).to receive(:new).and_return(redis) }

    it 'pings redis and reports healthy' do
      allow(redis).to receive(:ping).and_return('PONG')

      result = described_class.check_redis

      expect(result[:status]).to eq('healthy')
      expect(redis).to have_received(:close)
    end

    it 'builds the url from REDIS_HOST and REDIS_PORT' do
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('REDIS_HOST', 'localhost').and_return('redis.internal')
      allow(ENV).to receive(:fetch).with('REDIS_PORT', '6379').and_return('6380')
      allow(ENV).to receive(:fetch).with('REDIS_URL', 'redis://redis.internal:6380/0')
                                   .and_return('redis://redis.internal:6380/0')
      allow(redis).to receive(:ping)

      described_class.check_redis

      expect(Redis).to have_received(:new).with(url: 'redis://redis.internal:6380/0', timeout: 2)
    end

    it 'reports unhealthy when the client cannot be built' do
      allow(Redis).to receive(:new).and_raise(Redis::CannotConnectError, 'no route')

      expect(described_class.check_redis).to include(status: 'unhealthy', message: /no route/)
    end

    it 'reports unhealthy when redis is unreachable' do
      allow(redis).to receive(:ping).and_raise(Redis::CannotConnectError, 'refused')

      expect(described_class.check_redis).to include(status: 'unhealthy', message: /refused/)
      expect(redis).to have_received(:close)
    end
  end

  describe '.check_all' do
    let(:healthy) { described_class::ServiceStatus.new(name: 'x', status: 'healthy', latency_ms: 1.0) }
    let(:unhealthy) do
      described_class::ServiceStatus.new(name: 'y', status: 'unhealthy', latency_ms: 2.0, message: 'e')
    end

    before do
      allow(described_class).to receive_messages(
        check_database: { status: 'healthy', latency_ms: 0.5 },
        check_redis: { status: 'healthy', latency_ms: 0.4 }
      )
    end

    it 'is healthy when every service is healthy' do
      allow(described_class).to receive(:check_service).and_return(healthy)

      result = described_class.check_all

      expect(result[:status]).to eq('healthy')
      expect(result[:services].size).to eq(described_class::SERVICES.size)
      expect(result[:services].first).to include(name: 'x', status: 'healthy', latency_ms: 1.0)
      expect(result[:database]).to eq(status: 'healthy', latency_ms: 0.5)
      expect(result[:redis]).to eq(status: 'healthy', latency_ms: 0.4)
    end

    it 'is degraded when any service is unhealthy' do
      allow(described_class).to receive(:check_service).and_return(healthy, unhealthy)

      expect(described_class.check_all[:status]).to eq('degraded')
    end
  end
end
