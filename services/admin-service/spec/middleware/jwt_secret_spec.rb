require 'rails_helper'

RSpec.describe JwtSecret do
  let(:credentials_class) { Struct.new(:jwt_secret) }
  let(:no_credentials) { credentials_class.new(nil) }
  let(:random_secret) { SecureRandom.hex(32) }

  def resolve(env: {}, credentials: no_credentials, rails_env: 'production')
    described_class.resolve(env: env, credentials: credentials, rails_env: rails_env,
                            test_fallback: -> { 'checked-in-test-secret' })
  end

  %w[production development].each do |rails_env|
    context "in #{rails_env}" do
      it 'refuses to start without JWT_SECRET' do
        expect { resolve(rails_env: rails_env) }
          .to raise_error(JwtSecret::InsecureSecretError, /JWT_SECRET is not set/)
      end

      it 'refuses to start with an empty JWT_SECRET' do
        expect { resolve(env: { 'JWT_SECRET' => '' }, rails_env: rails_env) }
          .to raise_error(JwtSecret::InsecureSecretError, /JWT_SECRET is not set/)
      end

      JwtSecret::KNOWN_DEFAULTS.each do |default|
        it "refuses the published default #{default}" do
          expect { resolve(env: { 'JWT_SECRET' => default }, rails_env: rails_env) }
            .to raise_error(JwtSecret::InsecureSecretError, /published in the OtterWorks repository/)
        end
      end

      it 'refuses a secret shorter than 32 bytes' do
        expect { resolve(env: { 'JWT_SECRET' => 'a' * 31 }, rails_env: rails_env) }
          .to raise_error(JwtSecret::InsecureSecretError, /at least 32 bytes/)
      end

      it 'accepts a random secret from the environment' do
        expect(resolve(env: { 'JWT_SECRET' => random_secret }, rails_env: rails_env)).to eq(random_secret)
      end
    end
  end

  it 'prefers a credentials secret over the environment' do
    credentials = credentials_class.new(random_secret)
    expect(resolve(env: { 'JWT_SECRET' => SecureRandom.hex(32) }, credentials: credentials)).to eq(random_secret)
  end

  it 'validates a credentials secret too' do
    credentials = credentials_class.new('otterworks-local-dev-jwt-secret-change-me-in-production')
    expect { resolve(credentials: credentials) }.to raise_error(JwtSecret::InsecureSecretError)
  end

  it 'lets only the test environment fall back to secrets.yml' do
    expect(resolve(rails_env: 'test')).to eq('checked-in-test-secret')
  end

  it 'still rejects a published default in the test environment' do
    expect { resolve(env: { 'JWT_SECRET' => 'otterworks-dev-secret' }, rails_env: 'test') }
      .to raise_error(JwtSecret::InsecureSecretError)
  end
end
