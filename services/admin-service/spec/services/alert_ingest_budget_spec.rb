require 'rails_helper'

RSpec.describe AlertIngestBudget do
  let(:counts) { Hash.new(0) }
  let(:redis) { instance_double(Redis, close: nil) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(redis).to receive(:multi) do |&block|
      key = nil
      tx = double('tx') # rubocop:disable RSpec/VerifiedDoubles
      allow(tx).to receive(:incr) { |k| key = k }
      allow(tx).to receive(:expire)
      block.call(tx)
      [counts[key] += 1, true]
    end
  end

  around do |example|
    previous = ENV.to_h.slice('ALERT_DEDUP_BYPASS_PER_HOUR', 'ALERT_DEVIN_SESSIONS_PER_HOUR')
    ENV['ALERT_DEDUP_BYPASS_PER_HOUR'] = '2'
    ENV['ALERT_DEVIN_SESSIONS_PER_HOUR'] = '1'
    example.run
  ensure
    %w[ALERT_DEDUP_BYPASS_PER_HOUR ALERT_DEVIN_SESSIONS_PER_HOUR].each { |k| ENV.delete(k) }
    previous.each { |k, v| ENV[k] = v }
  end

  it 'allows dedup bypasses up to the hourly limit per service' do
    results = Array.new(3) { described_class.allow_dedup_bypass?('file-service') }
    expect(results).to eq([true, true, false])
    expect(described_class.allow_dedup_bypass?('notification-service')).to be(true)
  end

  it 'caps Devin sessions per hour across services' do
    expect([described_class.allow_devin_session?, described_class.allow_devin_session?]).to eq([true, false])
  end

  it 'treats the budget as spent when Redis is unavailable' do
    allow(redis).to receive(:multi).and_raise(Redis::CannotConnectError)
    expect(described_class.allow_devin_session?).to be(false)
    expect(described_class.allow_dedup_bypass?('file-service')).to be(false)
  end

  it 'falls back to the default limit for a non-numeric setting' do
    ENV['ALERT_DEVIN_SESSIONS_PER_HOUR'] = 'lots'
    expect(described_class.limit(:devin_session)).to eq(10)
  end
end
