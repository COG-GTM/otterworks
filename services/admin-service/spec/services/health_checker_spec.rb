require 'rails_helper'

RSpec.describe HealthChecker do
  let(:db_detail) { 'connection to server at "db.internal" (10.0.4.7), port 5432 failed for user "otterworks"' }
  let(:redis_detail) { 'Error connecting to Redis on redis.internal:6379' }
  let(:service_detail) { 'connect(2) for "auth-service.internal" port 8081' }

  before { allow(Rails.logger).to receive(:warn) }

  def stub_database_failure
    connection = ActiveRecord::Base.connection
    allow(connection).to receive(:execute).and_call_original
    allow(connection).to receive(:execute).with('SELECT 1')
                                          .and_raise(ActiveRecord::ConnectionNotEstablished, db_detail)
  end

  describe '.check_service' do
    it 'returns a generic message and logs the detail when the probe raises' do
      allow(Net::HTTP).to receive(:new).and_raise(Errno::ECONNREFUSED, service_detail)

      status = described_class.check_service('auth-service')

      expect(status.status).to eq('unhealthy')
      expect(status.message).to eq(HealthChecker::FAILURE_MESSAGE)
      expect(Rails.logger).to have_received(:warn).with(include('auth-service.internal'))
    end
  end

  describe '.check_database' do
    it 'does not expose the database error text' do
      stub_database_failure

      result = described_class.check_database

      expect(result).to eq(status: 'unhealthy', message: HealthChecker::FAILURE_MESSAGE)
      expect(Rails.logger).to have_received(:warn).with(include('db.internal'))
    end
  end

  describe '.check_redis' do
    it 'does not expose the redis error text' do
      redis = instance_double(Redis, close: nil)
      allow(Redis).to receive(:new).and_return(redis)
      allow(redis).to receive(:ping).and_raise(Redis::CannotConnectError, redis_detail)

      result = described_class.check_redis

      expect(result).to eq(status: 'unhealthy', message: HealthChecker::FAILURE_MESSAGE)
      expect(Rails.logger).to have_received(:warn).with(include('redis.internal'))
    end
  end

  describe '.check_all' do
    it 'never includes raw exception messages in the report' do
      allow(Net::HTTP).to receive(:new).and_raise(SocketError, service_detail)
      stub_database_failure
      allow(Redis).to receive(:new).and_raise(Redis::CannotConnectError, redis_detail)

      report = described_class.check_all

      expect(report[:status]).to eq('degraded')
      expect(report.to_json).not_to match(/internal|5432|6379|otterworks/)
    end
  end
end
