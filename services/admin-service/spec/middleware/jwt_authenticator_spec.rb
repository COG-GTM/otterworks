require 'rails_helper'

RSpec.describe JwtAuthenticator do
  let(:downstream_env) { {} }
  let(:app) do
    lambda { |env|
      downstream_env.replace(env)
      [200, { 'Content-Type' => 'text/plain' }, ['downstream']]
    }
  end
  let(:middleware) { described_class.new(app) }
  let(:user_id) { SecureRandom.uuid }

  def call(path, headers = {})
    middleware.call(Rack::MockRequest.env_for(path, headers))
  end

  describe '#call' do
    it 'passes an authenticated request downstream with the claims in env' do
      token = jwt_token(user_id: user_id, email: 'ops@otterworks.com', role: 'admin')

      status, _headers, body = call('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{token}")

      expect(status).to eq(200)
      expect(body).to eq(['downstream'])
      expect(downstream_env).to include(
        'jwt.user_id' => user_id,
        'jwt.user_email' => 'ops@otterworks.com',
        'jwt.user_role' => 'admin'
      )
      expect(downstream_env['jwt.payload']).to include('sub' => user_id)
    end

    it 'rejects a request with no Authorization header' do
      status, headers, body = call('/api/v1/admin/users')

      expect(status).to eq(401)
      expect(headers['Content-Type']).to eq('application/json')
      expect(JSON.parse(body.first)).to eq('error' => 'Missing authorization token')
      expect(downstream_env).to be_empty
    end

    it 'rejects a non-bearer Authorization header' do
      status, _headers, body = call('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => 'Basic abc123')

      expect(status).to eq(401)
      expect(JSON.parse(body.first)['error']).to eq('Missing authorization token')
    end

    it 'rejects a token signed with the wrong secret' do
      bogus = JWT.encode({ sub: user_id, exp: 1.hour.from_now.to_i }, 'not-the-secret', 'HS256')
      allow(Rails.logger).to receive(:warn)

      status, _headers, body = call('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{bogus}")

      expect(status).to eq(401)
      expect(JSON.parse(body.first)['error']).to eq('Invalid or expired token')
      expect(Rails.logger).to have_received(:warn).with(/JWT authentication failed/)
    end

    it 'rejects an expired token' do
      expired = JWT.encode({ sub: user_id, exp: 1.hour.ago.to_i },
                           Rails.application.secrets.jwt_secret, 'HS256')
      allow(Rails.logger).to receive(:warn)

      status, = call('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{expired}")

      expect(status).to eq(401)
    end

    it 'prefers the JWT_SECRET environment variable when credentials are unset' do
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('JWT_SECRET', Rails.application.secrets.jwt_secret).and_return('env-secret')
      token = JWT.encode({ sub: user_id, email: 'e@x.com', role: 'viewer', exp: 1.hour.from_now.to_i },
                         'env-secret', 'HS256')

      status, = call('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{token}")

      expect(status).to eq(200)
      expect(downstream_env['jwt.user_id']).to eq(user_id)
    end

    described_class::EXCLUDED_PATHS.each do |path|
      it "skips authentication for #{path}" do
        status, _headers, body = call(path)

        expect(status).to eq(200)
        expect(body).to eq(['downstream'])
        expect(downstream_env).not_to have_key('jwt.user_id')
      end
    end
  end
end
