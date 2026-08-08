require 'rails_helper'

# Complements spec/models/storage_quota_spec.rb by covering the zero-quota guard.
RSpec.describe StorageQuota do
  describe '#usage_percentage with a zero quota' do
    it 'returns zero instead of dividing by zero' do
      expect(build(:storage_quota, quota_bytes: 0, used_bytes: 10).usage_percentage).to eq(0)
    end
  end
end
