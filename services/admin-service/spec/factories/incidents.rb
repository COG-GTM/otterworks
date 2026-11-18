FactoryBot.define do
  factory :incident do
    title { 'File upload failed' }
    description { 'S3 PutObject returned 500' }
    severity { 'high' }
    status { 'open' }
    affected_service { 'file-service' }

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

    trait :with_session do
      sequence(:devin_session_id) { |n| "devin-session-#{n}" }
      devin_session_url { "https://app.devin.ai/sessions/#{devin_session_id}" }
      devin_session_status { 'running' }
    end
  end
end
