require 'rails_helper'

RSpec.describe JwtAuthenticator do
  let(:secret) { Rails.application.secrets.jwt_secret }
  let(:app) { ->(env) { [200, {}, [env['jwt.user_email'].to_s]] } }
  let(:payload) { { sub: SecureRandom.uuid, email: 'admin@otterworks.com', role: 'super_admin' } }

  def call(token)
    env = Rack::MockRequest.env_for('/api/v1/admin/incidents',
                                    'HTTP_AUTHORIZATION' => "Bearer #{token}")
    described_class.new(app).call(env)
  end

  %w[HS256 HS384 HS512].each do |algorithm|
    it "accepts a token signed with #{algorithm}" do
      status, _headers, body = call(JWT.encode(payload, secret, algorithm))
      expect(status).to eq(200)
      expect(body.first).to eq('admin@otterworks.com')
    end
  end

  it "normalizes auth-service's uppercase `roles` array to one lowercase role" do
    role_app = ->(env) { [200, {}, [env['jwt.user_role'].to_s]] }
    env = Rack::MockRequest.env_for(
      '/api/v1/admin/incidents',
      'HTTP_AUTHORIZATION' =>
        "Bearer #{JWT.encode({ sub: SecureRandom.uuid, roles: %w[USER ADMIN] }, secret, 'HS512')}"
    )
    _status, _headers, body = described_class.new(role_app).call(env)
    expect(body.first).to eq('admin')
  end

  it 'rejects a token signed with the wrong secret' do
    status, _headers, body = call(JWT.encode(payload, 'not-the-secret', 'HS512'))
    expect(status).to eq(401)
    expect(JSON.parse(body.first)['error']).to eq('Invalid or expired token')
  end

  context 'outside the test environment' do
    before { allow(Rails).to receive(:env).and_return(ActiveSupport::EnvironmentInquirer.new('development')) }

    it 'verifies with JWT_SECRET from the environment' do
      stub_const('ENV', ENV.to_h.merge('JWT_SECRET' => 'per-deploy-secret'))
      status, _headers, _body = call(JWT.encode(payload, 'per-deploy-secret', 'HS512'))
      expect(status).to eq(200)
    end

    it 'rejects every token instead of falling back to a committed default when JWT_SECRET is unset' do
      stub_const('ENV', ENV.to_h.except('JWT_SECRET'))
      [secret, 'dev_jwt_secret_key', 'otterworks-local-dev-jwt-secret-change-me-in-production'].each do |guess|
        status, _headers, body = call(JWT.encode(payload, guess, 'HS256'))
        expect(status).to eq(401)
        expect(JSON.parse(body.first)['error']).to eq('Invalid or expired token')
      end
    end
  end
end
