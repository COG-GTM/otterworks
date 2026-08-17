require 'rails_helper'

RSpec.describe DevinSecretsManagerSource do
  let(:client) { instance_double(Aws::SecretsManager::Client) }

  before do
    described_class.reset_cache!
    described_class.instance_variable_set(:@client, client)
    ENV['DEVIN_CREDENTIALS_SECRET_ID'] = 'otterworks/dev/devin'
  end

  after do
    ENV.delete('DEVIN_CREDENTIALS_SECRET_ID')
    described_class.reset_cache!
    described_class.instance_variable_set(:@client, nil)
  end

  def secret(body)
    instance_double(Aws::SecretsManager::Types::GetSecretValueResponse, secret_string: body)
  end

  it 'is disabled when no secret id is configured' do
    ENV.delete('DEVIN_CREDENTIALS_SECRET_ID')

    expect(described_class).not_to be_enabled
    expect(described_class.credentials).to eq({ api_key: nil, org_id: nil })
  end

  it 'reads the pair from the secret' do
    allow(client).to receive(:get_secret_value)
      .with(secret_id: 'otterworks/dev/devin')
      .and_return(secret({ api_key: 'sm-key', org_id: 'sm-org' }.to_json))

    expect(described_class.credentials).to eq({ api_key: 'sm-key', org_id: 'sm-org' })
  end

  it 'caches so every incident does not call AWS' do
    allow(client).to receive(:get_secret_value)
      .and_return(secret({ api_key: 'sm-key', org_id: 'sm-org' }.to_json))

    3.times { described_class.credentials }

    expect(client).to have_received(:get_secret_value).once
  end

  it 'keeps serving the last good pair when Secrets Manager fails' do
    allow(client).to receive(:get_secret_value)
      .and_return(secret({ api_key: 'sm-key', org_id: 'sm-org' }.to_json))
    described_class.credentials
    described_class.instance_variable_get(:@cache)[:fetched_at] = 0
    allow(client).to receive(:get_secret_value).and_raise(StandardError, 'throttled')

    expect(described_class.credentials).to eq({ api_key: 'sm-key', org_id: 'sm-org' })
  end

  it 'reports nothing when the secret is unreadable and nothing was cached' do
    allow(client).to receive(:get_secret_value).and_raise(StandardError, 'denied')

    expect(described_class.credentials).to eq({ api_key: nil, org_id: nil })
  end

  it 'ignores a half-populated secret' do
    allow(client).to receive(:get_secret_value).and_return(secret({ api_key: 'sm-key' }.to_json))

    expect(described_class.credentials).to eq({ api_key: 'sm-key', org_id: nil })
  end
end
