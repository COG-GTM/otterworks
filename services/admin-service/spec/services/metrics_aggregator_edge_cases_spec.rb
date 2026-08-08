require 'rails_helper'

RSpec.describe MetricsAggregator do
  describe '.summary' do
    it 'reports zero average usage when no quotas exist' do
      expect(described_class.summary[:storage][:average_usage_percent]).to eq(0)
    end

    it 'reports zero average usage when the aggregate is undefined' do
      create(:storage_quota)
      allow(StorageQuota).to receive(:average).and_return(nil)

      expect(described_class.summary[:storage][:average_usage_percent]).to eq(0)
    end

    it 'rounds the average usage across quotas' do
      create(:storage_quota, quota_bytes: 100, used_bytes: 25)
      create(:storage_quota, quota_bytes: 100, used_bytes: 75)

      expect(described_class.summary[:storage][:average_usage_percent]).to eq(50.0)
    end
  end
end
