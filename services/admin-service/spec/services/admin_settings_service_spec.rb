require 'rails_helper'

RSpec.describe AdminSettingsService do
  let(:redis) { instance_double(Redis, mget: [nil, nil], del: 0, close: nil) }

  before { allow(Redis).to receive(:new).and_return(redis) }

  describe '.set_devin_credentials' do
    it 'stores the pair durably and masks it from the config API' do
      described_class.set_devin_credentials(api_key: 'key-1', org_id: 'org-1')

      expect(described_class.devin_credentials).to eq({ api_key: 'key-1', org_id: 'org-1' })
      expect(SystemConfig.find_by(key: 'devin_api_key')).to be_is_secret
      expect(SystemConfig.public_configs.pluck(:key)).not_to include('devin_api_key')
    end

    it 'overwrites a previously stored pair' do
      described_class.set_devin_credentials(api_key: 'old', org_id: 'org-1')
      described_class.set_devin_credentials(api_key: 'new', org_id: 'org-2')

      expect(described_class.devin_credentials).to eq({ api_key: 'new', org_id: 'org-2' })
    end

    it 'still stores when the cache of legacy keys is unreachable' do
      allow(redis).to receive(:del).and_raise(Redis::BaseError, 'down')

      described_class.set_devin_credentials(api_key: 'key-1', org_id: 'org-1')

      expect(described_class.devin_credentials).to eq({ api_key: 'key-1', org_id: 'org-1' })
    end
  end

  describe '.devin_credentials' do
    it 'reports nothing configured when neither store holds a pair' do
      expect(described_class.devin_credentials).to eq({ api_key: nil, org_id: nil })
    end

    it 'adopts a pair left in Redis by the previous store' do
      allow(redis).to receive(:mget).and_return(%w[legacy-key legacy-org])

      expect(described_class.devin_credentials).to eq({ api_key: 'legacy-key', org_id: 'legacy-org' })
      expect(SystemConfig.find_by(key: 'devin_api_key').value).to eq('legacy-key')
      expect(redis).to have_received(:del).with('admin:devin_api_key', 'admin:devin_org_id')
    end

    it 'still returns the legacy pair when adopting it fails' do
      allow(redis).to receive(:mget).and_return(%w[legacy-key legacy-org])
      allow(described_class).to receive(:set_devin_credentials)
        .and_raise(ActiveRecord::StatementInvalid, 'db down')

      expect(described_class.devin_credentials).to eq({ api_key: 'legacy-key', org_id: 'legacy-org' })
    end

    it 'does not adopt a legacy pair while the revocation marker is unreadable' do
      allow(redis).to receive(:mget).and_return(%w[legacy-key legacy-org])
      allow(SystemConfig).to receive(:exists?).and_raise(ActiveRecord::StatementInvalid, 'db down')

      expect(described_class.devin_credentials).to eq({ api_key: nil, org_id: nil })
    end

    it 'ignores a half-populated legacy pair' do
      allow(redis).to receive(:mget).and_return(['legacy-key', nil])

      expect(described_class.devin_credentials).to eq({ api_key: nil, org_id: nil })
      expect(SystemConfig.where(key: 'devin_api_key')).to be_empty
    end
  end

  describe '.clear_devin_credentials' do
    it 'removes the stored pair' do
      described_class.set_devin_credentials(api_key: 'key-1', org_id: 'org-1')
      described_class.clear_devin_credentials

      expect(described_class.devin_credentials).to eq({ api_key: nil, org_id: nil })
    end

    it 'revokes durably and reports the cache copy as not cleared when Redis is down' do
      described_class.set_devin_credentials(api_key: 'key-1', org_id: 'org-1')
      allow(redis).to receive(:del).and_raise(Redis::BaseError, 'down')

      expect(described_class.clear_devin_credentials).to be(false)
      expect(SystemConfig.where(key: 'devin_api_key')).to be_empty
    end

    it 'does not re-adopt a legacy pair that survived a revoke' do
      allow(redis).to receive(:del).and_raise(Redis::BaseError, 'down')
      described_class.clear_devin_credentials
      allow(redis).to receive(:mget).and_return(%w[legacy-key legacy-org])

      expect(described_class.devin_credentials).to eq({ api_key: nil, org_id: nil })
    end

    it 'adopts again once credentials are deliberately set after a revoke' do
      allow(redis).to receive(:del).and_raise(Redis::BaseError, 'down')
      described_class.clear_devin_credentials
      allow(redis).to receive(:del).and_return(2)
      described_class.set_devin_credentials(api_key: 'key-2', org_id: 'org-2')

      expect(described_class.devin_credentials).to eq({ api_key: 'key-2', org_id: 'org-2' })
    end
  end
end
