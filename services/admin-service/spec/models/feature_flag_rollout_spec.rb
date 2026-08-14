require 'rails_helper'

# Complements spec/models/feature_flag_spec.rb with the percentage rollout bucketing.
RSpec.describe FeatureFlag do
  describe '#enabled_for_user?' do
    let(:flag) { create(:feature_flag, :partial_rollout, name: 'partial_feature') }

    def bucket_for(user_id)
      Digest::MD5.hexdigest("#{flag.name}:#{user_id}").hex % 100
    end

    it 'includes a user whose bucket falls under the rollout percentage' do
      user_id = (1..500).map(&:to_s).find { |id| bucket_for(id) < flag.rollout_percentage }

      expect(user_id).to be_present
      expect(flag.enabled_for_user?(user_id)).to be(true)
    end

    it 'excludes a user whose bucket falls above the rollout percentage' do
      user_id = (1..500).map(&:to_s).find { |id| bucket_for(id) >= flag.rollout_percentage }

      expect(user_id).to be_present
      expect(flag.enabled_for_user?(user_id)).to be(false)
    end

    it 'buckets a user by an md5 of the flag name and user id' do
      user_id = 'stable-user'
      reloaded = described_class.find(flag.id)

      expect(flag.enabled_for_user?(user_id)).to be(bucket_for(user_id) < flag.rollout_percentage)
      expect(reloaded.enabled_for_user?(user_id)).to eq(flag.enabled_for_user?(user_id))
    end

    it 'excludes everybody once the flag has expired' do
      expired = create(:feature_flag, :expired, rollout_percentage: 100)

      expect(expired).to be_expired
      expect(expired.enabled_for_user?('anyone')).to be(false)
    end

    it 'excludes everybody at a zero percent rollout' do
      zero = create(:feature_flag, enabled: true, rollout_percentage: 0)

      expect(zero.enabled_for_user?('anyone')).to be(false)
    end
  end
end
