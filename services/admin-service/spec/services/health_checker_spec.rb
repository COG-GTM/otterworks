require 'rails_helper'

RSpec.describe HealthChecker do
  let(:redis) { instance_double(Redis, ping: 'PONG', close: nil) }

  before { allow(Redis).to receive(:new).and_return(redis) }

  describe '.check_service' do
    let(:http) { instance_double(Net::HTTP, :open_timeout= => nil, :read_timeout= => nil) }

    before { allow(Net::HTTP).to receive(:new).and_return(http) }

    it 'reports healthy on a 200 using default host and port' do
      allow(http).to receive(:get).with('/health').and_return(instance_double(Net::HTTPOK, code: '200'))
      status = described_class.check_service('auth-service')
      expect(Net::HTTP).to have_received(:new).with('auth-service', 8081)
      expect(status.status).to eq('healthy')
      expect(status.latency_ms).to be >= 0
    end

    it 'honours host/port env overrides including k8s link-style ports' do
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('FILE_SERVICE_HOST', 'file-service').and_return('files.internal')
      allow(ENV).to receive(:fetch).with('FILE_SERVICE_PORT', nil).and_return('tcp://10.0.0.1:9999')
      allow(http).to receive(:get).and_return(instance_double(Net::HTTPOK, code: '200'))

      described_class.check_service('file-service')

      expect(Net::HTTP).to have_received(:new).with('files.internal', 9999)
    end

    it 'reports unhealthy on a non-200' do
      allow(http).to receive(:get).and_return(instance_double(Net::HTTPServiceUnavailable, code: '503'))
      expect(described_class.check_service('search-service').status).to eq('unhealthy')
    end

    it 'reports unhealthy with the error message when the request fails' do
      allow(http).to receive(:get).and_raise(Errno::ECONNREFUSED)
      status = described_class.check_service('search-service')
      expect(status.status).to eq('unhealthy')
      expect(status.message).to include('Connection refused')
    end

    it 'reports unknown when no port is configured' do
      status = described_class.check_service('unlisted-service')
      expect(status.to_h).to include(status: 'unknown', latency_ms: 0, message: 'No endpoint configured')
      expect(Net::HTTP).not_to have_received(:new)
    end
  end

  describe '.check_database' do
    it 'reports healthy' do
      expect(described_class.check_database).to include(status: 'healthy')
    end

    it 'reports unhealthy on error' do
      allow(ActiveRecord::Base.connection).to receive(:execute).and_raise(ActiveRecord::ConnectionNotEstablished, 'db down')
      expect(described_class.check_database).to eq({ status: 'unhealthy', message: 'db down' })
    end
  end

  describe '.check_redis' do
    it 'reports healthy and closes the connection' do
      expect(described_class.check_redis).to include(status: 'healthy')
      expect(redis).to have_received(:close)
    end

    it 'reports unhealthy on error' do
      allow(redis).to receive(:ping).and_raise(Redis::CannotConnectError, 'redis down')
      expect(described_class.check_redis).to eq({ status: 'unhealthy', message: 'redis down' })
    end
  end

  describe '.check_all' do
    def stub_services(status)
      allow(described_class).to receive(:check_service) do |name|
        HealthChecker::ServiceStatus.new(name: name, status: status, latency_ms: 1.0)
      end
    end

    it 'is healthy when every service is healthy' do
      stub_services('healthy')
      result = described_class.check_all
      expect(result[:status]).to eq('healthy')
      expect(result[:services].map { |s| s[:name] }).to eq(HealthChecker::SERVICES)
      expect(result[:database][:status]).to eq('healthy')
      expect(result[:redis][:status]).to eq('healthy')
    end

    it 'is degraded when any service is not healthy' do
      stub_services('unhealthy')
      expect(described_class.check_all[:status]).to eq('degraded')
    end
  end
end
