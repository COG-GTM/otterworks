require 'rails_helper'

RSpec.describe JwtAuthenticator do
  let(:downstream_response) { [200, { 'Content-Type' => 'application/json' }, ['{}']] }
  let(:app) { ->(env) { captured_envs << env and downstream_response } }
  let(:captured_envs) { [] }
  let(:middleware) { described_class.new(app) }

  def env_for(path, headers = {})
    Rack::MockRequest.env_for(path).merge(headers)
  end

  describe 'excluded paths' do
    described_class::EXCLUDED_PATHS.each do |path|
      it "passes #{path} straight through" do
        status, = middleware.call(env_for(path))

        expect(status).to eq(200)
        expect(captured_envs.first).not_to have_key('jwt.user_id')
      end
    end
  end

  describe 'missing or malformed credentials' do
    it 'returns 401 without an Authorization header' do
      status, headers, body = middleware.call(env_for('/api/v1/admin/users'))

      expect(status).to eq(401)
      expect(headers['Content-Type']).to eq('application/json')
      expect(JSON.parse(body.first)['error']).to eq('Missing authorization token')
      expect(captured_envs).to be_empty
    end

    it 'returns 401 for a non-bearer scheme' do
      status, = middleware.call(env_for('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => 'Basic abc'))

      expect(status).to eq(401)
    end

    it 'returns 401 for a token that does not verify' do
      allow(Rails.logger).to receive(:warn)

      status, _headers, body = middleware.call(
        env_for('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => 'Bearer not-a-jwt')
      )

      expect(status).to eq(401)
      expect(JSON.parse(body.first)['error']).to eq('Invalid or expired token')
      expect(Rails.logger).to have_received(:warn).with(/JWT authentication failed/)
    end

    it 'returns 401 for an expired token' do
      allow(Rails.logger).to receive(:warn)
      expired = JWT.encode({ sub: 'u1', exp: 1.hour.ago.to_i }, Rails.application.secrets.jwt_secret, 'HS256')

      status, = middleware.call(env_for('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{expired}"))

      expect(status).to eq(401)
    end
  end

  describe 'a valid token' do
    it 'decorates the env with the JWT claims and calls the app' do
      token = jwt_token(user_id: 'user-1', email: 'admin@otterworks.com', role: 'super_admin')

      status, = middleware.call(env_for('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{token}"))

      expect(status).to eq(200)
      env = captured_envs.first
      expect(env['jwt.user_id']).to eq('user-1')
      expect(env['jwt.user_email']).to eq('admin@otterworks.com')
      expect(env['jwt.user_role']).to eq('super_admin')
      expect(env['jwt.payload']).to include('sub' => 'user-1')
    end

    it 'prefers the JWT_SECRET environment variable over the app secrets' do
      allow(ENV).to receive(:fetch).and_call_original
      allow(ENV).to receive(:fetch).with('JWT_SECRET', anything).and_return('env-secret')
      token = JWT.encode({ sub: 'user-2', exp: 1.hour.from_now.to_i }, 'env-secret', 'HS256')

      status, = middleware.call(env_for('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => "Bearer #{token}"))

      expect(status).to eq(200)
      expect(captured_envs.first['jwt.user_id']).to eq('user-2')
    end
  end
end
