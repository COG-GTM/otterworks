require 'rails_helper'

RSpec.describe JwtAuthenticator do
  # The helper signs with Rails.application.secrets.jwt_secret, which the middleware
  # only falls back to when JWT_SECRET is unset (the compose container sets one).
  around { |example| with_env('JWT_SECRET' => nil) { example.run } }

  let(:downstream) do
    lambda do |env|
      [200, { 'Content-Type' => 'application/json' }, [env.slice('jwt.user_id', 'jwt.user_email',
                                                                 'jwt.user_role').to_json]]
    end
  end
  let(:middleware) { described_class.new(downstream) }
  let(:user_id) { SecureRandom.uuid }

  def call(path, headers = {})
    middleware.call(Rack::MockRequest.env_for(path, headers))
  end

  describe 'excluded paths' do
    # EXCLUDED_PATHS also covers the alert-webhook and chaos endpoints, which are
    # guarded by their own shared secrets rather than by JWT.
    it 'passes every excluded path through without a token' do
      described_class::EXCLUDED_PATHS.each do |path|
        status, = call(path)

        expect(status).to eq(200)
      end
    end
  end

  describe 'missing or malformed credentials' do
    it 'returns 401 when the Authorization header is absent' do
      status, headers, body = call('/api/v1/admin/users')

      expect(status).to eq(401)
      expect(headers['Content-Type']).to eq('application/json')
      expect(JSON.parse(body.first)['error']).to eq('Missing authorization token')
    end

    it 'returns 401 when the scheme is not Bearer' do
      status, _headers, body = call('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => 'Basic abc123')

      expect(status).to eq(401)
      expect(JSON.parse(body.first)['error']).to eq('Missing authorization token')
    end

    it 'returns 401 and logs when the token is not decodable' do
      allow(Rails.logger).to receive(:warn)

      status, _headers, body = call('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => 'Bearer garbage')

      expect(status).to eq(401)
      expect(JSON.parse(body.first)['error']).to eq('Invalid or expired token')
      expect(Rails.logger).to have_received(:warn).with(/JWT authentication failed/)
    end

    it 'returns 401 for an expired token' do
      allow(Rails.logger).to receive(:warn)
      secret = Rails.application.secrets.jwt_secret
      expired = JWT.encode({ sub: user_id, exp: 1.hour.ago.to_i }, secret, 'HS256')

      status, = call('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{expired}")

      expect(status).to eq(401)
    end

    it 'returns 401 for a token signed with the wrong key' do
      allow(Rails.logger).to receive(:warn)
      forged = JWT.encode({ sub: user_id, exp: 1.hour.from_now.to_i }, 'not-the-secret', 'HS256')

      status, = call('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{forged}")

      expect(status).to eq(401)
    end
  end

  describe 'a valid token' do
    it 'exposes the claims to the downstream app' do
      token = jwt_token(user_id: user_id, email: 'ops@otterworks.com', role: 'admin')

      status, _headers, body = call('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{token}")

      expect(status).to eq(200)
      expect(JSON.parse(body.first)).to eq(
        'jwt.user_id' => user_id,
        'jwt.user_email' => 'ops@otterworks.com',
        'jwt.user_role' => 'admin'
      )
    end
  end
end
