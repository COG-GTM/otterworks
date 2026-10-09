require 'rails_helper'

RSpec.describe JwtAuthenticator do
  let(:secret) { Rails.application.secrets.jwt_secret }
  let(:app) { ->(env) { [200, {}, [env['jwt.user_email'].to_s]] } }
  let(:binding_claims) { { iss: described_class.issuer, aud: described_class.audience } }
  let(:payload) do
    binding_claims.merge(sub: SecureRandom.uuid, email: 'admin@otterworks.com', role: 'super_admin')
  end

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
        "Bearer #{JWT.encode(binding_claims.merge(sub: SecureRandom.uuid, roles: %w[USER ADMIN]), secret, 'HS512')}"
    )
    _status, _headers, body = described_class.new(role_app).call(env)
    expect(body.first).to eq('admin')
  end

  it 'rejects a token signed with the wrong secret' do
    status, _headers, body = call(JWT.encode(payload, 'not-the-secret', 'HS512'))
    expect(status).to eq(401)
    expect(JSON.parse(body.first)['error']).to eq('Invalid or expired token')
  end

  context 'when the token is not bound to this tenant' do
    {
      'another tenant audience' => { aud: 'otterworks-t-other' },
      'a foreign issuer' => { iss: 'evil-issuer' },
      'no audience' => { aud: nil },
      'no issuer' => { iss: nil }
    }.each do |label, overrides|
      it "rejects an OWNER token with #{label}, even when signed with the shared secret" do
        claims = payload.merge(roles: %w[OWNER]).merge(overrides).compact
        status, _headers, body = call(JWT.encode(claims, secret, 'HS512'))
        expect(status).to eq(401)
        expect(JSON.parse(body.first)['error']).to eq('Invalid or expired token')
      end
    end
  end

  it 'honours the tenant audience configured via JWT_AUDIENCE' do
    allow(ENV).to receive(:[]).and_call_original
    allow(ENV).to receive(:[]).with('JWT_AUDIENCE').and_return('otterworks-t-a')
    tenant_a = JWT.encode(payload.merge(aud: 'otterworks-t-a'), secret, 'HS512')
    tenant_b = JWT.encode(payload.merge(aud: 'otterworks-t-b'), secret, 'HS512')

    expect(call(tenant_a).first).to eq(200)
    expect(call(tenant_b).first).to eq(401)
  end
end
