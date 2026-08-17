require 'rails_helper'

RSpec.describe JwtAuthenticator do
  subject(:middleware) { described_class.new(app) }

  let(:downstream_response) { [200, { 'Content-Type' => 'application/json' }, ['{}']] }
  let(:app) do
    lambda do |env|
      @env = env
      downstream_response
    end
  end
  let(:secret) do
    Rails.application.credentials.jwt_secret || ENV.fetch('JWT_SECRET', Rails.application.secrets.jwt_secret)
  end

  def env_for(path, headers = {})
    Rack::MockRequest.env_for(path).merge(headers)
  end

  def token_for(payload)
    JWT.encode(payload, secret, 'HS256')
  end

  describe 'excluded paths' do
    it 'passes health checks straight through' do
      expect(middleware.call(env_for('/health'))).to eq(downstream_response)
      expect(@env).not_to have_key('jwt.user_id')
    end

    it 'passes the alert webhook straight through' do
      expect(middleware.call(env_for('/api/v1/admin/alerts/ingest'))).to eq(downstream_response)
    end
  end

  describe 'authenticated requests' do
    it 'exposes the decoded claims to the app' do
      user_id = SecureRandom.uuid
      token = token_for({ sub: user_id, email: 'admin@otterworks.com', role: 'super_admin',
                          exp: 1.hour.from_now.to_i })

      status, = middleware.call(env_for('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{token}"))

      expect(status).to eq(200)
      expect(@env['jwt.user_id']).to eq(user_id)
      expect(@env['jwt.user_email']).to eq('admin@otterworks.com')
      expect(@env['jwt.user_role']).to eq('super_admin')
      expect(@env['jwt.payload']).to include('sub' => user_id)
    end
  end

  describe 'rejected requests' do
    it 'returns 401 when the Authorization header is missing' do
      status, headers, body = middleware.call(env_for('/api/v1/admin/users'))

      expect(status).to eq(401)
      expect(headers['Content-Type']).to eq('application/json')
      expect(JSON.parse(body.first)['error']).to eq('Missing authorization token')
    end

    it 'returns 401 when the scheme is not Bearer' do
      status, _headers, body = middleware.call(
        env_for('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => 'Basic abc')
      )

      expect(status).to eq(401)
      expect(JSON.parse(body.first)['error']).to eq('Missing authorization token')
    end

    it 'returns 401 for a token signed with the wrong secret' do
      allow(Rails.logger).to receive(:warn)
      token = JWT.encode({ sub: 'x', exp: 1.hour.from_now.to_i }, 'not-the-secret', 'HS256')

      status, _headers, body = middleware.call(
        env_for('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{token}")
      )

      expect(status).to eq(401)
      expect(JSON.parse(body.first)['error']).to eq('Invalid or expired token')
      expect(Rails.logger).to have_received(:warn).with(/JWT authentication failed/)
    end

    it 'returns 401 for an expired token' do
      allow(Rails.logger).to receive(:warn)
      token = token_for({ sub: 'x', exp: 1.hour.ago.to_i })

      status, = middleware.call(env_for('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{token}"))

      expect(status).to eq(401)
    end
  end
end
