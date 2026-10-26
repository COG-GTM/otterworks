require 'rails_helper'

RSpec.describe AlertIncidentBudget do
  let(:store) { {} }
  let(:redis) { instance_double(Redis, close: nil) }
  let(:args) { { alert_name: 'FileUploadFailed', affected_service: 'file-service', reporter_email: 'm@example.com' } }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(redis).to receive(:set) { |key, value, **| store[key] ||= value }
    allow(redis).to receive(:incr) { |key| store[key] = store.fetch(key, 0) + 1 }
  end

  it 'allows up to the limit per reporter, then refuses' do
    results = Array.new(described_class::DEFAULT_LIMIT + 2) { described_class.allow?(**args) }
    expect(results.count(true)).to eq(described_class::DEFAULT_LIMIT)
    expect(results.last(2)).to eq([false, false])
  end

  it 'keeps a separate budget per reporter, case-insensitively' do
    described_class::DEFAULT_LIMIT.times { described_class.allow?(**args) }
    expect(described_class.allow?(**args, reporter_email: 'M@EXAMPLE.COM')).to be(false)
    expect(described_class.allow?(**args, reporter_email: 'other@example.com')).to be(true)
  end

  it 'sets the window expiry only when the counter is created' do
    described_class.allow?(**args)
    expect(redis).to have_received(:set)
      .with(a_string_starting_with('admin:alert_dedup_bypass:'), 0, ex: 3600, nx: true)
  end

  it 'does not put the raw reporter email in the Redis key' do
    described_class.allow?(**args)
    expect(store.keys).to all(satisfy { |key| !key.include?('m@example.com') })
  end

  it 'honours ALERT_DEDUP_BYPASS_LIMIT and ignores invalid values' do
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('ALERT_DEDUP_BYPASS_LIMIT', nil).and_return('2')
    expect(described_class.limit).to eq(2)
    allow(ENV).to receive(:fetch).with('ALERT_DEDUP_BYPASS_LIMIT', nil).and_return('-1')
    expect(described_class.limit).to eq(described_class::DEFAULT_LIMIT)
  end

  it 'refuses (falls back to dedup) when Redis is unreachable' do
    allow(redis).to receive(:set).and_raise(Redis::CannotConnectError)
    expect(described_class.allow?(**args)).to be(false)
  end
end
