require 'rails_helper'

RSpec.describe AlertIngestBudget do
  let(:counts) { Hash.new(0) }
  let(:redis) { instance_double(Redis, close: nil) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(redis).to receive(:multi) do |&block|
      tx = double('tx')
      key = nil
      allow(tx).to receive(:incr) { |k| key = k }
      allow(tx).to receive(:expire)
      block.call(tx)
      [counts[key] += 1, true]
    end
  end

  around do |example|
    previous = ENV.fetch('ALERT_DEDUP_BYPASS_PER_HOUR', nil)
    ENV['ALERT_DEDUP_BYPASS_PER_HOUR'] = '2'
    example.run
  ensure
    previous.nil? ? ENV.delete('ALERT_DEDUP_BYPASS_PER_HOUR') : ENV['ALERT_DEDUP_BYPASS_PER_HOUR'] = previous
  end

  it 'allows bypasses up to the hourly limit per service' do
    results = Array.new(3) { described_class.allow_dedup_bypass?('file-service') }
    expect(results).to eq([true, true, false])
    expect(described_class.allow_dedup_bypass?('notification-service')).to be(true)
  end

  it 'denies the bypass when Redis is unavailable' do
    allow(redis).to receive(:multi).and_raise(Redis::CannotConnectError)
    expect(described_class.allow_dedup_bypass?('file-service')).to be(false)
  end

  it 'falls back to the default limit for a non-numeric setting' do
    ENV['ALERT_DEDUP_BYPASS_PER_HOUR'] = 'lots'
    expect(described_class.limit).to eq(described_class::DEFAULT_LIMIT)
  end
end
