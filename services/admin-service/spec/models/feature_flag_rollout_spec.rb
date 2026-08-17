require 'rails_helper'

RSpec.describe FeatureFlag do
  describe '#enabled_for_user?' do
    let(:flag) { create(:feature_flag, :partial_rollout, name: 'partial_feature') }

    def bucket_for(user_id)
      Digest::MD5.hexdigest("#{flag.name}:#{user_id}").hex % 100
    end

    it 'enables the flag for a user inside the rollout bucket' do
      user_id = (1..500).map(&:to_s).find { |id| bucket_for(id) < flag.rollout_percentage }

      expect(flag.enabled_for_user?(user_id)).to be(true)
    end

    it 'leaves the flag off for a user outside the rollout bucket' do
      user_id = (1..500).map(&:to_s).find { |id| bucket_for(id) >= flag.rollout_percentage }

      expect(flag.enabled_for_user?(user_id)).to be(false)
    end

    it 'leaves the flag off for everyone at 0% rollout' do
      zero = create(:feature_flag, name: 'zero_feature', enabled: true, rollout_percentage: 0)

      expect(zero.enabled_for_user?('any-user')).to be(false)
    end
  end
end
