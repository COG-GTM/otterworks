module EnvHelper
  # Sets environment variables for the duration of the block and always restores
  # the original environment afterwards (examples run in random order).
  def with_env(vars)
    original = ENV.to_hash
    vars.each do |key, value|
      if value.nil?
        ENV.delete(key.to_s)
      else
        ENV[key.to_s] = value
      end
    end
    yield
  ensure
    ENV.replace(original)
  end
end

RSpec.configure do |config|
  config.include EnvHelper
end
