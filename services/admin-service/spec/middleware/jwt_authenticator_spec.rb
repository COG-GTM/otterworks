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

  it 'rejects a token signed with the wrong secret' do
    status, _headers, body = call(JWT.encode(payload, 'not-the-secret', 'HS512'))
    expect(status).to eq(401)
    expect(JSON.parse(body.first)['error']).to eq('Invalid or expired token')
  end
end
