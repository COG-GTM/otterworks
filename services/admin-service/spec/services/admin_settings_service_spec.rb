require 'rails_helper'

RSpec.describe AdminSettingsService do
  describe '.reserve_dedup_bypass' do
    let(:redis) { instance_double(Redis, close: nil) }
    let(:tx) { double('Redis::MultiConnection') } # rubocop:disable RSpec/VerifiedDoubles

    before do
      allow(Redis).to receive(:new).and_return(redis)
      allow(tx).to receive(:set)
      allow(tx).to receive(:incr)
    end

    def reserve_with_count(count)
      allow(redis).to receive(:multi) do |&block|
        block.call(tx)
        [true, count]
      end
      described_class.reserve_dedup_bypass('file-service', limit: 2, window: 10.minutes)
    end

    it 'allows reservations up to the limit' do
      expect(reserve_with_count(2)).to be(true)
      expect(tx).to have_received(:set).with('alerts:dedup_bypass:file-service', 0, ex: 600, nx: true)
      expect(tx).to have_received(:incr).with('alerts:dedup_bypass:file-service')
    end

    it 'denies reservations past the limit' do
      expect(reserve_with_count(3)).to be(false)
    end

    it 'fails closed when Redis is unavailable' do
      allow(redis).to receive(:multi).and_raise(Redis::CannotConnectError)
      expect(described_class.reserve_dedup_bypass('file-service', limit: 2, window: 10.minutes)).to be(false)
    end
  end
end
