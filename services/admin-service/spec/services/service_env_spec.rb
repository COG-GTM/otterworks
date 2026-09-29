require 'rails_helper'

RSpec.describe ServiceEnv do
  def with_env(vars)
    previous = vars.keys.to_h { |k| [k, ENV.fetch(k, nil)] }
    vars.each { |k, v| v.nil? ? ENV.delete(k) : ENV[k] = v }
    yield
  ensure
    previous.each { |k, v| v.nil? ? ENV.delete(k) : ENV[k] = v }
  end

  describe '.port' do
    it 'returns the default when unset or empty' do
      expect(described_class.port('MISSING_PORT', '6379')).to eq('6379')
      with_env('REDIS_PORT' => '') { expect(described_class.port('REDIS_PORT', '6379')).to eq('6379') }
    end

    it 'passes a plain port through' do
      with_env('REDIS_PORT' => '6380') { expect(described_class.port('REDIS_PORT', '6379')).to eq('6380') }
    end

    it 'takes the port out of the Kubernetes service-link form' do
      with_env('REDIS_PORT' => 'tcp://172.20.229.93:6379') do
        expect(described_class.port('REDIS_PORT', '1')).to eq('6379')
      end
    end

    it 'falls back to the default for an unparseable value' do
      with_env('REDIS_PORT' => 'tcp://172.20.229.93') do
        expect(described_class.port('REDIS_PORT', '6379')).to eq('6379')
      end
    end
  end

  describe '.redis_url' do
    it 'builds a usable URL when Kubernetes shadows REDIS_PORT' do
      with_env('REDIS_URL' => nil, 'REDIS_HOST' => 'redis', 'REDIS_PORT' => 'tcp://172.20.229.93:6379') do
        expect(described_class.redis_url).to eq('redis://redis:6379/0')
      end
    end

    it 'prefers an explicit REDIS_URL' do
      with_env('REDIS_URL' => 'redis://elsewhere:6379/1', 'REDIS_HOST' => 'redis') do
        expect(described_class.redis_url).to eq('redis://elsewhere:6379/1')
      end
    end
  end
end
