require 'rails_helper'

RSpec.describe ChaosProbeService do
  let(:redis_key) { 'chaos:search-service:suggest_500' }
  let(:active) { Concurrent::AtomicBoolean.new(true) }
  let(:redis) { instance_double(Redis, close: nil) }

  before do
    stub_const('ChaosProbeService::PROBE_INTERVAL', 0.01)
    allow(redis).to receive(:exists?).with(redis_key) { active.true? }
    allow(Redis).to receive(:new).and_return(redis)
    allow(described_class).to receive(:fire_probe)
  end

  after do
    active.make_false
    described_class.instance_variable_get(:@probes).values.each { |t| t.join(2) }
  end

  it 'reuses the running probe for repeated triggers of the same key' do
    first = described_class.start(service: 'search-service', redis_key: redis_key)
    second = described_class.start(service: 'search-service', redis_key: redis_key)

    expect(second).to equal(first)
    expect(Redis).to have_received(:new).at_most(:once)
  end

  it 'starts a new probe once the previous one has stopped' do
    first = described_class.start(service: 'search-service', redis_key: redis_key)
    active.make_false
    first.join(2)
    expect(described_class.running?(redis_key)).to be(false)

    active.make_true
    second = described_class.start(service: 'search-service', redis_key: redis_key)

    expect(second).not_to equal(first)
    expect(described_class.running?(redis_key)).to be(true)
  end

  it 'ignores unknown services' do
    expect(described_class.start(service: 'auth-service', redis_key: 'chaos:auth-service:x')).to be_nil
  end
end
