FactoryBot.define do
  factory :sharing_policy do
    workspace_id { SharingPolicy::DEFAULT_WORKSPACE_ID }
    default_expiry_days { 30 }
    min_expiry_days { 1 }
    max_expiry_days { 90 }
  end
end
