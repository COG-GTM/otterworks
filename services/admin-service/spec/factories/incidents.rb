FactoryBot.define do
  factory :incident do
    title { Faker::Lorem.sentence(word_count: 5) }
    description { Faker::Lorem.paragraph }
    severity { 'medium' }
    status { 'open' }
    affected_service { 'search-service' }

    trait :investigating do
      status { 'investigating' }
    end

    trait :resolved do
      status { 'resolved' }
      resolved_at { 1.hour.ago }
    end

    trait :closed do
      status { 'closed' }
      resolved_at { 2.hours.ago }
      closed_at { 1.hour.ago }
    end

    trait :critical do
      severity { 'critical' }
    end

    trait :with_devin_session do
      devin_session_id { "devin-#{SecureRandom.hex(6)}" }
      devin_session_url { 'https://app.devin.ai/sessions/abc123' }
      devin_session_status { 'running' }
    end
  end
end
