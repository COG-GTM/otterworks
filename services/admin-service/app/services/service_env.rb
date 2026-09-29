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

  def redis_url
    url = ENV.fetch('REDIS_URL', nil).to_s
    return url unless url.empty?

    "redis://#{ENV.fetch('REDIS_HOST', 'localhost')}:#{port('REDIS_PORT', '6379')}/0"
  end
end
