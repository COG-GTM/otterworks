require 'rails_helper'

RSpec.describe MetricsAggregator do
  describe '.summary' do
    it 'reports zeroed metrics for an empty system' do
      summary = described_class.summary

      expect(summary[:users]).to include(total: 0, active: 0, suspended: 0, by_role: {})
      expect(summary[:storage]).to include(total_allocated_bytes: 0, average_usage_percent: 0, users_over_quota: 0)
      expect(summary[:features]).to include(total: 0, enabled: 0, disabled: 0)
      expect(summary[:announcements]).to include(total: 0, active: 0)
      expect(summary[:audit]).to include(total_events: 0, events_today: 0)
      expect(summary[:timestamp]).to be_present
    end

    it 'aggregates users, storage, flags, announcements and audit events' do
      create(:admin_user, :admin)
      create(:admin_user, :suspended)
      create(:storage_quota, quota_bytes: 100, used_bytes: 50)
      create(:storage_quota, :over_quota, quota_bytes: 100, used_bytes: 150)
      create(:feature_flag, :enabled)
      create(:announcement, :published)
      create(:audit_log)

      summary = described_class.summary

      expect(summary[:users]).to include(total: 2, active: 1, suspended: 1)
      expect(summary[:users][:by_role]).to include('admin' => 1)
      expect(summary[:storage]).to include(total_allocated_bytes: 200, total_used_bytes: 200,
                                           average_usage_percent: 100.0, users_over_quota: 1)
      expect(summary[:features]).to include(total: 1, enabled: 1, disabled: 0)
      expect(summary[:announcements]).to include(total: 1, active: 1)
      expect(summary[:audit][:total_events]).to eq(1)
      expect(summary[:audit][:top_actions]).to include('user.updated' => 1)
    end

    it 'falls back to zero when every quota row has an unusable denominator' do
      quota = create(:storage_quota)
      quota.update_column(:quota_bytes, 0)

      expect(described_class.summary[:storage][:average_usage_percent]).to eq(0)
    end
  end
end
