require 'simplecov'
SimpleCov.start 'rails' do
  enable_coverage :branch

  add_filter '/spec/'
  add_filter '/config/'
  add_filter '/db/'

  # Ratchet: pinned to what the suite actually achieves (line 100%, branch 91.86%).
  # Policy target is line >= 95 / branch >= 85. Never lower these.
  minimum_coverage line: 100, branch: 90
end

RSpec.configure do |config|
  config.expect_with :rspec do |expectations|
    expectations.include_chain_clauses_in_custom_matcher_descriptions = true
  end

  config.mock_with :rspec do |mocks|
    mocks.verify_partial_doubles = true
  end

  config.shared_context_metadata_behavior = :apply_to_host_groups
  config.order = :random
  Kernel.srand config.seed
end
