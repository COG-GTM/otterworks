require 'rails_helper'

RSpec.describe AdminSettingsService do
  let(:redis) { instance_double(Redis, close: nil) }

  before { allow(Redis).to receive(:new).and_return(redis) }

  describe '.auto_investigate_enabled?' do
    it 'defaults to true when the key is unset' do
      allow(redis).to receive(:get).with(described_class::AUTO_INVESTIGATE_KEY).and_return(nil)

      expect(described_class.auto_investigate_enabled?).to be(true)
      expect(redis).to have_received(:close)
    end

    it 'returns true when the stored value is "true"' do
      allow(redis).to receive(:get).and_return('true')

      expect(described_class.auto_investigate_enabled?).to be(true)
    end

    it 'returns false when the stored value is not "true"' do
      allow(redis).to receive(:get).and_return('false')

      expect(described_class.auto_investigate_enabled?).to be(false)
    end

    it 'fails open when the redis client cannot even be built' do
      allow(Redis).to receive(:new).and_raise(Redis::CannotConnectError, 'no route')
      allow(Rails.logger).to receive(:error)

      expect(described_class.auto_investigate_enabled?).to be(true)
      expect(Rails.logger).to have_received(:error).with(/no route/)
    end

    it 'fails open and logs when redis raises' do
      allow(redis).to receive(:get).and_raise(Redis::BaseConnectionError, 'boom')
      allow(Rails.logger).to receive(:error)

      expect(described_class.auto_investigate_enabled?).to be(true)
      expect(Rails.logger).to have_received(:error).with(/boom/)
      expect(redis).to have_received(:close)
    end
  end

  describe '.set_auto_investigate' do
    it 'writes the stringified flag' do
      allow(redis).to receive(:set)

      described_class.set_auto_investigate(false)

      expect(redis).to have_received(:set).with(described_class::AUTO_INVESTIGATE_KEY, 'false')
      expect(redis).to have_received(:close)
    end

    it 're-raises when the redis client cannot be built' do
      allow(Redis).to receive(:new).and_raise(Redis::CannotConnectError, 'no route')
      allow(Rails.logger).to receive(:error)

      expect { described_class.set_auto_investigate(true) }.to raise_error(Redis::CannotConnectError)
    end

    it 're-raises after logging when redis fails' do
      allow(redis).to receive(:set).and_raise(Redis::BaseConnectionError, 'down')
      allow(Rails.logger).to receive(:error)

      expect { described_class.set_auto_investigate(true) }.to raise_error(Redis::BaseConnectionError)
      expect(Rails.logger).to have_received(:error).with(/down/)
      expect(redis).to have_received(:close)
    end
  end
end
