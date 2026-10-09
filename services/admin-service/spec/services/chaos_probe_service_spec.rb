require 'rails_helper'

RSpec.describe ChaosProbeService do
  let(:redis) { instance_double(Redis) }
  let(:key_state) { { present: true } }

  before do
    stub_const('ChaosProbeService::PROBE_INTERVAL', 0.01)
    allow(redis).to receive(:exists?) { key_state[:present] }
    allow(redis).to receive(:close)
    allow(Redis).to receive(:new).and_return(redis)
    allow(described_class).to receive(:fire_probe)
  end

  after do
    key_state[:present] = false
    wait_until { described_class.running_count.zero? }
  end

  def wait_until(timeout: 2)
    deadline = Time.current + timeout
    sleep 0.01 until yield || Time.current > deadline
  end

  it 'returns nil for a service without a probe' do
    expect(described_class.start(service: 'auth-service', redis_key: 'chaos:auth-service:x')).to be_nil
    expect(described_class.running_count).to eq(0)
  end

  it 'runs at most one probe per service no matter how often it is triggered' do
    results = Array.new(50) do
      described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500')
    end

    expect(results.first).to eq(:started)
    expect(results.drop(1)).to all(eq(:already_running))
    expect(described_class.running_count).to eq(1)
  end

  it 'deduplicates concurrent triggers for the same service' do
    results = Array.new(20) do
      Thread.new { described_class.start(service: 'file-service', redis_key: 'chaos:file-service:upload_s3_error') }
    end.map(&:value)

    expect(results.count(:started)).to eq(1)
    expect(results.count(:already_running)).to eq(19)
    expect(described_class.running_count).to eq(1)
  end

  it 'releases the slot when the chaos key goes away so a later trigger can start a new probe' do
    key = 'chaos:search-service:suggest_500'
    expect(described_class.start(service: 'search-service', redis_key: key)).to eq(:started)

    key_state[:present] = false
    wait_until { !described_class.running?('search-service') }
    expect(described_class.running?('search-service')).to be(false)

    key_state[:present] = true
    expect(described_class.start(service: 'search-service', redis_key: key)).to eq(:started)
  end

  it 'refuses new probes once the global cap is reached' do
    stub_const('ChaosProbeService::MAX_CONCURRENT_PROBES', 2)

    expect(described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500'))
      .to eq(:started)
    expect(described_class.start(service: 'file-service', redis_key: 'chaos:file-service:upload_s3_error'))
      .to eq(:started)
    expect(described_class.start(service: 'document-service', redis_key: 'chaos:document-service:slow_queries'))
      .to eq(:at_capacity)
    expect(described_class.running_count).to eq(2)
  end

  it 'keeps the default cap at one probe per known service' do
    expect(described_class::MAX_CONCURRENT_PROBES).to eq(described_class::SERVICE_PROBES.size)
  end
end
