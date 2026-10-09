require 'rails_helper'

RSpec.describe DevinSessionThrottle do
  let(:redis) { instance_double(Redis, close: nil, expire: true) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('ALERT_DEVIN_SESSIONS_PER_HOUR', anything).and_return('2')
  end

  it 'allows sessions up to the hourly limit' do
    allow(redis).to receive(:incr).and_return(1, 2, 3)

    expect([described_class.acquire, described_class.acquire, described_class.acquire]).to eq([true, true, false])
    expect(redis).to have_received(:expire).once
  end

  it 'fails closed when Redis is unavailable' do
    allow(redis).to receive(:incr).and_raise(Redis::CannotConnectError)

    expect(described_class.acquire).to be(false)
  end
end
