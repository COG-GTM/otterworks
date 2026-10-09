require 'rails_helper'

RSpec.describe AdminSettingsService do
  describe '.auto_investigate_enabled?' do
    let(:redis) { instance_double(Redis, close: nil) }

    before { allow(Redis).to receive(:new).and_return(redis) }

    it 'defaults to enabled when the setting was never stored' do
      allow(redis).to receive(:get).and_return(nil)

      expect(described_class.auto_investigate_enabled?).to be(true)
    end

    it 'fails closed when the setting cannot be read' do
      allow(redis).to receive(:get).and_raise(Redis::CannotConnectError)

      expect(described_class.auto_investigate_enabled?).to be(false)
    end
  end
end
