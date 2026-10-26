require 'rails_helper'

RSpec.describe ChaosIncidentRegistry do
  let(:redis) { instance_double(Redis, close: nil, sadd: 1, expire: true) }

  before { allow(Redis).to receive(:new).and_return(redis) }

  def incident(service)
    Incident.create!(title: 't', description: 'd', severity: 'high', status: 'open', affected_service: service)
  end

  it 'records an incident opened while the service chaos flag is set' do
    allow(redis).to receive(:exists?).with('chaos:file-service:upload_s3_error').and_return(true)
    inc = incident('file-service')

    expect(described_class.record(inc)).to be(true)
    expect(redis).to have_received(:sadd).with('chaos_incidents:file-service', inc.id)
    expect(redis).to have_received(:expire).with('chaos_incidents:file-service', described_class::TTL_SECONDS)
  end

  it 'does not record an incident when no chaos flag is set' do
    allow(redis).to receive(:exists?).and_return(false)

    expect(described_class.record(incident('file-service'))).to be(false)
    expect(redis).not_to have_received(:sadd)
  end

  it 'ignores services without a chaos scenario' do
    expect(described_class.record(incident('auth-service'))).to be(false)
    expect(Redis).not_to have_received(:new)
  end

  it 'does not raise when Redis is unavailable' do
    allow(redis).to receive(:exists?).and_raise(Redis::CannotConnectError)

    expect(described_class.record(incident('file-service'))).to be(false)
  end
end
