require 'rails_helper'

RSpec.describe AdminSettingsService do
  let(:redis) { instance_double(Redis, close: nil) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(Rails.logger).to receive(:error)
  end

  shared_examples 'a fail-open boolean flag' do |reader, key|
    it 'defaults to true when unset' do
      allow(redis).to receive(:get).with(key).and_return(nil)
      expect(described_class.public_send(reader)).to be true
      expect(redis).to have_received(:close)
    end

    it 'is true when stored as "true"' do
      allow(redis).to receive(:get).with(key).and_return('true')
      expect(described_class.public_send(reader)).to be true
    end

    it 'is false when stored as anything else' do
      allow(redis).to receive(:get).with(key).and_return('false')
      expect(described_class.public_send(reader)).to be false
    end

    it 'fails open when Redis is unreachable' do
      allow(redis).to receive(:get).and_raise(Redis::CannotConnectError, 'down')
      expect(described_class.public_send(reader)).to be true
      expect(Rails.logger).to have_received(:error).with(/down/)
      expect(redis).to have_received(:close)
    end

    it 'fails open when the client cannot be built' do
      allow(Redis).to receive(:new).and_raise(ArgumentError, 'bad url')
      expect(described_class.public_send(reader)).to be true
    end
  end

  shared_examples 'a raising writer' do |writer, args, redis_call|
    it 'writes to Redis and closes the connection' do
      allow(redis).to receive(redis_call).and_return('OK')
      described_class.public_send(writer, *args[:positional], **args[:keyword])
      expect(redis).to have_received(redis_call).with(*args[:expected])
      expect(redis).to have_received(:close)
    end

    it 'logs and re-raises Redis errors' do
      allow(redis).to receive(redis_call).and_raise(Redis::CannotConnectError, 'down')
      expect { described_class.public_send(writer, *args[:positional], **args[:keyword]) }
        .to raise_error(Redis::CannotConnectError)
      expect(Rails.logger).to have_received(:error).with(/down/)
      expect(redis).to have_received(:close)
    end
  end

  describe '.auto_investigate_enabled?' do
    it_behaves_like 'a fail-open boolean flag', :auto_investigate_enabled?, 'admin:auto_investigate'
  end

  describe '.slack_notifications_enabled?' do
    it_behaves_like 'a fail-open boolean flag', :slack_notifications_enabled?, 'admin:slack_notifications'
  end

  describe '.set_auto_investigate' do
    it_behaves_like 'a raising writer', :set_auto_investigate,
                    { positional: [false], keyword: {}, expected: ['admin:auto_investigate', 'false'] }, :set
  end

  describe '.set_slack_notifications' do
    it_behaves_like 'a raising writer', :set_slack_notifications,
                    { positional: [true], keyword: {}, expected: ['admin:slack_notifications', 'true'] }, :set
  end

  describe '.set_devin_credentials' do
    it_behaves_like 'a raising writer', :set_devin_credentials,
                    { positional: [], keyword: { api_key: 'k', org_id: 'o' },
                      expected: ['admin:devin_api_key', 'k', 'admin:devin_org_id', 'o'] }, :mset
  end

  describe '.clear_devin_credentials' do
    it_behaves_like 'a raising writer', :clear_devin_credentials,
                    { positional: [], keyword: {}, expected: ['admin:devin_api_key', 'admin:devin_org_id'] }, :del
  end

  describe '.set_slack_webhook_url' do
    it_behaves_like 'a raising writer', :set_slack_webhook_url,
                    { positional: ['https://hooks.slack.com/x'], keyword: {},
                      expected: ['admin:slack_webhook_url', 'https://hooks.slack.com/x'] }, :set
  end

  describe '.set_slack_bot_token' do
    it_behaves_like 'a raising writer', :set_slack_bot_token,
                    { positional: ['xoxb-1'], keyword: {}, expected: ['admin:slack_bot_token', 'xoxb-1'] }, :set
  end

  describe '.clear_slack_credentials' do
    it_behaves_like 'a raising writer', :clear_slack_credentials,
                    { positional: [], keyword: {}, expected: ['admin:slack_webhook_url', 'admin:slack_bot_token'] }, :del
  end

  describe '.devin_credentials' do
    it 'returns stored values' do
      allow(redis).to receive(:mget).with('admin:devin_api_key', 'admin:devin_org_id').and_return(%w[key org])
      expect(described_class.devin_credentials).to eq({ api_key: 'key', org_id: 'org' })
    end

    it 'normalizes blank values to nil' do
      allow(redis).to receive(:mget).and_return(['  ', nil])
      expect(described_class.devin_credentials).to eq({ api_key: nil, org_id: nil })
    end

    it 'returns nils when Redis fails' do
      allow(redis).to receive(:mget).and_raise(Redis::CannotConnectError, 'down')
      expect(described_class.devin_credentials).to eq({ api_key: nil, org_id: nil })
      expect(Rails.logger).to have_received(:error).with(/down/)
    end
  end

  { slack_webhook_url: 'admin:slack_webhook_url', slack_bot_token: 'admin:slack_bot_token' }.each do |reader, key|
    describe ".#{reader}" do
      it 'returns the stored value' do
        allow(redis).to receive(:get).with(key).and_return('secret-value')
        expect(described_class.public_send(reader)).to eq('secret-value')
      end

      it 'returns nil for a blank value' do
        allow(redis).to receive(:get).with(key).and_return('')
        expect(described_class.public_send(reader)).to be_nil
      end

      it 'returns nil when Redis fails' do
        allow(redis).to receive(:get).and_raise(Redis::CannotConnectError, 'down')
        expect(described_class.public_send(reader)).to be_nil
        expect(redis).to have_received(:close)
      end
    end
  end
end
