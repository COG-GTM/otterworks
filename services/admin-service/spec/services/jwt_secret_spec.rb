require 'rails_helper'

RSpec.describe JwtSecret do
  describe '.validate!' do
    it 'rejects a missing secret' do
      expect { described_class.validate!(nil) }.to raise_error(JwtSecret::InsecureSecretError, /required/)
      expect { described_class.validate!('  ') }.to raise_error(JwtSecret::InsecureSecretError, /required/)
    end

    it 'rejects every placeholder secret that has shipped in the repo' do
      JwtSecret::KNOWN_INSECURE.each do |secret|
        expect { described_class.validate!(secret) }.to raise_error(JwtSecret::InsecureSecretError, /placeholder/)
      end
    end

    it 'accepts a generated secret' do
      expect { described_class.validate!(SecureRandom.hex(32)) }.not_to raise_error
    end
  end

  describe '.current' do
    it 'prefers JWT_SECRET from the environment' do
      previous = ENV.fetch('JWT_SECRET', nil)
      ENV['JWT_SECRET'] = 'from-env'
      allow(Rails.application.credentials).to receive(:jwt_secret).and_return(nil)
      expect(described_class.current).to eq('from-env')
    ensure
      previous.nil? ? ENV.delete('JWT_SECRET') : ENV['JWT_SECRET'] = previous
    end
  end
end
