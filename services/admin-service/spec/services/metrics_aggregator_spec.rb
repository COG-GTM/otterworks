require 'rails_helper'

RSpec.describe MetricsAggregator do
  describe '.summary with an empty database' do
    it 'reports zeroed metrics without dividing by zero' do
      summary = described_class.summary

      expect(summary[:timestamp]).to be_present
      expect(summary[:users]).to include(total: 0, active: 0, suspended: 0)
      expect(summary[:storage]).to include(total_allocated_bytes: 0, average_usage_percent: 0, users_over_quota: 0)
      expect(summary[:features]).to include(total: 0, enabled: 0, disabled: 0)
      expect(summary[:announcements]).to include(total: 0, active: 0)
      expect(summary[:audit]).to include(total_events: 0, events_today: 0, events_this_week: 0)
    end
  end

  describe '.summary with data' do
    it 'averages storage usage across quotas' do
      create(:storage_quota, quota_bytes: 100, used_bytes: 25)
      create(:storage_quota, quota_bytes: 100, used_bytes: 75)

      expect(described_class.summary[:storage][:average_usage_percent]).to eq(50.0)
    end
  end
end
