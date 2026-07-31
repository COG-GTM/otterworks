require 'rails_helper'

RSpec.describe FeatureFlag do
  describe '#enabled_for_user?' do
    let(:user_id) { '00000000-0000-0000-0000-000000000001' }

    def bucket_for(name, id)
      Digest::MD5.hexdigest("#{name}:#{id}").hex % 100
    end

    it 'is false for an expired flag even when enabled' do
      flag = build(:feature_flag, :expired, rollout_percentage: 100)

      expect(flag.enabled_for_user?(user_id)).to be(false)
    end

    it 'is false when the rollout percentage is zero' do
      flag = build(:feature_flag, enabled: true, rollout_percentage: 0)

      expect(flag.enabled_for_user?(user_id)).to be(false)
    end

    it 'includes users whose hash bucket falls under the rollout percentage' do
      bucket = bucket_for('gradual_rollout', user_id)
      flag = build(:feature_flag, name: 'gradual_rollout', enabled: true, rollout_percentage: bucket + 1)

      expect(bucket).to eq(19)
      expect(flag.enabled_for_user?(user_id)).to be(true)
    end

    it 'excludes users whose hash bucket is at or above the rollout percentage' do
      bucket = bucket_for('gradual_rollout', user_id)
      flag = build(:feature_flag, name: 'gradual_rollout', enabled: true, rollout_percentage: bucket)

      expect(flag.enabled_for_user?(user_id)).to be(false)
    end
  end
end
