require 'erb'

# Kubernetes injects Docker-link style variables for every Service in the
# namespace, so a Service named `redis` gives the pod
# REDIS_PORT="tcp://172.20.229.93:6379" -- which shadows the plain port number
# this service expects and yields "redis://redis:tcp://172.20.229.93:6379/0".
# Read ports through here so the link form resolves to the port it carries.
module ServiceEnv
  module_function

  def port(name, default)
    raw = ENV.fetch(name, nil).to_s
    return default if raw.empty?
    return raw if raw.match?(/\A\d+\z/)

    raw[/:(\d+)\z/, 1] || default
  end

  # REDIS_PASSWORD (AUTH token) and REDIS_TLS=true are set for the shared
  # ElastiCache, which rejects unauthenticated and plaintext connections.
  def redis_url
    url = ENV.fetch('REDIS_URL', nil).to_s
    return url unless url.empty?

    scheme = truthy?(ENV.fetch('REDIS_TLS', nil)) ? 'rediss' : 'redis'
    password = ENV.fetch('REDIS_PASSWORD', nil).to_s
    userinfo = password.empty? ? '' : ":#{ERB::Util.url_encode(password)}@"
    "#{scheme}://#{userinfo}#{ENV.fetch('REDIS_HOST', 'localhost')}:#{port('REDIS_PORT', '6379')}/0"
  end

  def truthy?(value)
    %w[1 true yes].include?(value.to_s.strip.downcase)
  end
end
