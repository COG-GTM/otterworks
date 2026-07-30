require 'rails_helper'

# Complements spec/models/storage_quota_spec.rb with the zero-quota guard.
RSpec.describe StorageQuota do
  describe '#usage_percentage' do
    it 'returns 0 rather than dividing by zero' do
      quota = build(:storage_quota, quota_bytes: 0, used_bytes: 10)

      expect(quota.usage_percentage).to eq(0)
    end

    it 'rounds the ratio to two decimals' do
      quota = build(:storage_quota, quota_bytes: 300, used_bytes: 100)

      expect(quota.usage_percentage).to eq(33.33)
    end
  end
end
