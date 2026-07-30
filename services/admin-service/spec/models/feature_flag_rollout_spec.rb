require 'rails_helper'

# Complements spec/models/feature_flag_spec.rb by covering the percentage
# bucketing branch of #enabled_for_user?.
RSpec.describe FeatureFlag do
  describe '#enabled_for_user? with a partial rollout' do
    let(:flag) { build(:feature_flag, :partial_rollout, name: 'partial_feature') }

    def bucket(user_id)
      Digest::MD5.hexdigest("partial_feature:#{user_id}").hex % 100
    end

    it 'includes users whose bucket falls under the percentage' do
      user_id = (1..500).map(&:to_s).find { |id| bucket(id) < 50 }

      expect(flag.enabled_for_user?(user_id)).to be(true)
    end

    it 'excludes users whose bucket falls above the percentage' do
      user_id = (1..500).map(&:to_s).find { |id| bucket(id) >= 50 }

      expect(flag.enabled_for_user?(user_id)).to be(false)
    end

    it 'excludes everyone at zero percent' do
      flag.rollout_percentage = 0

      expect(flag.enabled_for_user?('user-1')).to be(false)
    end

    it 'excludes everyone once the flag has expired' do
      flag.expires_at = 1.day.ago

      expect(flag.enabled_for_user?('user-1')).to be(false)
    end
  end
end
