require 'rails_helper'

RSpec.describe StorageQuota do
  describe '#usage_percentage' do
    it 'is zero when no quota is allocated' do
      expect(build(:storage_quota, quota_bytes: 0, used_bytes: 10).usage_percentage).to eq(0)
    end

    it 'is the rounded ratio of used to allocated bytes' do
      expect(build(:storage_quota, quota_bytes: 300, used_bytes: 100).usage_percentage).to eq(33.33)
    end
  end
end
