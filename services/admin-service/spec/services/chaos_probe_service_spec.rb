require 'rails_helper'

RSpec.describe ChaosProbeService do
  let!(:active_keys) { Set.new }
  let(:redis) { instance_double(Redis, close: nil) }
  let!(:probes_fired) { Concurrent::AtomicFixnum.new }

  def wait_until(timeout: 2)
    deadline = Time.now + timeout
    sleep 0.01 until yield || Time.now > deadline
  end

  before do
    stub_const('ChaosProbeService::PROBE_INTERVAL', 0.01)
    allow(Redis).to receive(:new).and_return(redis)
    allow(redis).to receive(:exists?) { |key| active_keys.include?(key) }
    allow(described_class).to receive(:fire_probe) { probes_fired.increment }
  end

  after do
    active_keys.clear
    wait_until { described_class.active_probe_count.zero? }
  end

  it 'ignores services without a probe' do
    expect(described_class.start(service: 'unknown-service', redis_key: 'chaos:unknown')).to be_nil
    expect(described_class.active_probe_count).to eq(0)
  end

  it 'runs at most one probe per service across repeated triggers' do
    active_keys << 'chaos:search-service:suggest_500'

    threads = Array.new(25) do
      described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500')
    end

    expect(threads.uniq.size).to eq(1)
    expect(described_class.active_probe_count).to eq(1)
  end

  it 'caps the number of concurrent probes' do
    stub_const('ChaosProbeService::MAX_CONCURRENT_PROBES', 2)
    %w[search-service file-service document-service].each { |svc| active_keys << "chaos:#{svc}" }

    expect(described_class.start(service: 'search-service', redis_key: 'chaos:search-service')).to be_a(Thread)
    expect(described_class.start(service: 'file-service', redis_key: 'chaos:file-service')).to be_a(Thread)
    expect(described_class.start(service: 'document-service', redis_key: 'chaos:document-service')).to be_nil
    expect(described_class.active_probe_count).to eq(2)
  end

  it 'deregisters a probe once its chaos key expires so a later trigger starts a new one' do
    key = 'chaos:search-service:suggest_500'
    active_keys << key
    first = described_class.start(service: 'search-service', redis_key: key)
    wait_until { probes_fired.value >= ChaosProbeService::PROBE_BATCH }

    active_keys.delete(key)
    expect(first.join(2)).to eq(first)
    expect(described_class.active_probe_count).to eq(0)

    active_keys << key
    second = described_class.start(service: 'search-service', redis_key: key)
    expect(second).to be_a(Thread)
    expect(second).not_to eq(first)
    expect(probes_fired.value).to be >= ChaosProbeService::PROBE_BATCH
  end
end
