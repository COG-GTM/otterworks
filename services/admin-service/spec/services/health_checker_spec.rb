require 'rails_helper'

RSpec.describe HealthChecker do
  let(:http) { instance_double(Net::HTTP, :open_timeout= => nil, :read_timeout= => nil) }
  let(:ok_response) { instance_double(Net::HTTPResponse, code: '200') }

  before do
    allow(Net::HTTP).to receive(:new).and_return(http)
    # Pin the environment so injected *_SERVICE_HOST/_PORT variables cannot change the defaults.
    stub_const('ENV', ENV.to_hash.except(*ENV.keys.grep(/_SERVICE_(HOST|PORT)\z/)))
  end

  describe '.check_service' do
    it 'reports a healthy service with a latency measurement' do
      allow(http).to receive(:get).with('/health').and_return(ok_response)

      status = described_class.check_service('auth-service')

      expect(status.name).to eq('auth-service')
      expect(status.status).to eq('healthy')
      expect(status.latency_ms).to be_a(Float)
      expect(Net::HTTP).to have_received(:new).with('auth-service', 8081)
    end

    it 'honours host and port overrides from the environment' do
      allow(http).to receive(:get).and_return(ok_response)
      stub_const('ENV', ENV.to_hash.merge('FILE_SERVICE_HOST' => 'files.internal', 'FILE_SERVICE_PORT' => '9999'))

      described_class.check_service('file-service')

      expect(Net::HTTP).to have_received(:new).with('files.internal', 9999)
    end

    it 'reports unhealthy on a non-200 response' do
      allow(http).to receive(:get).and_return(instance_double(Net::HTTPResponse, code: '503'))

      expect(described_class.check_service('file-service').status).to eq('unhealthy')
    end

    it 'reports unhealthy with the error message when the request raises' do
      allow(http).to receive(:get).and_raise(Errno::ECONNREFUSED, 'nobody home')

      status = described_class.check_service('search-service')

      expect(status.status).to eq('unhealthy')
      expect(status.message).to match(/nobody home/)
    end

    it 'reports unknown when no port is configured' do
      stub_const("#{described_class}::DEFAULT_PORTS", {})

      status = described_class.check_service('mystery-service')

      expect(status.status).to eq('unknown')
      expect(status.message).to eq('No endpoint configured')
      expect(status.latency_ms).to eq(0)
    end
  end

  describe '.check_database' do
    it 'reports healthy when the connection answers' do
      expect(described_class.check_database).to include(status: 'healthy')
    end

    it 'reports unhealthy when the query raises' do
      allow(ActiveRecord::Base.connection).to receive(:execute).and_raise(StandardError, 'no db')

      expect(described_class.check_database).to eq(status: 'unhealthy', message: 'no db')
    end
  end

  describe '.check_redis' do
    let(:redis) { instance_double(Redis, close: nil) }

    before { allow(Redis).to receive(:new).and_return(redis) }

    it 'reports healthy when redis answers a ping' do
      allow(redis).to receive(:ping).and_return('PONG')

      result = described_class.check_redis

      expect(result[:status]).to eq('healthy')
      expect(redis).to have_received(:close)
    end

    it 'reports unhealthy when redis raises' do
      allow(redis).to receive(:ping).and_raise(Redis::BaseConnectionError, 'refused')

      expect(described_class.check_redis).to include(status: 'unhealthy', message: /refused/)
    end
  end

  describe '.check_all' do
    let(:redis) { instance_double(Redis, ping: 'PONG', close: nil) }

    before { allow(Redis).to receive(:new).and_return(redis) }

    it 'reports healthy overall when every service answers' do
      allow(http).to receive(:get).and_return(ok_response)

      result = described_class.check_all

      expect(result[:status]).to eq('healthy')
      expect(result[:services].map { |s| s[:name] }).to eq(described_class::SERVICES)
      expect(result[:database][:status]).to eq('healthy')
      expect(result[:redis][:status]).to eq('healthy')
      expect(result[:timestamp]).to be_present
    end

    it 'reports degraded overall when one service is down' do
      allow(http).to receive(:get).and_return(ok_response, instance_double(Net::HTTPResponse, code: '500'))

      result = described_class.check_all

      expect(result[:status]).to eq('degraded')
    end
  end
end
