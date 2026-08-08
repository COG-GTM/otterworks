require 'rails_helper'

RSpec.describe ChaosProbeService do
  let(:redis) { instance_double(Redis, close: nil) }
  let(:http) { instance_double(Net::HTTP) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(http).to receive(:open_timeout=)
    allow(http).to receive(:read_timeout=)
    allow(http).to receive(:request).and_return(instance_double(Net::HTTPOK))
    allow(Net::HTTP).to receive(:new).and_return(http)
    allow(Rails.logger).to receive(:info)
    allow(Rails.logger).to receive(:error)
  end

  describe '.start' do
    it 'does nothing for an unknown service' do
      expect(described_class.start(service: 'nope-service', redis_key: 'chaos:nope')).to be_nil
      expect(Redis).not_to have_received(:new)
    end

    it 'stops immediately when the redis key is already gone' do
      allow(redis).to receive(:exists?).with('chaos:search-service:suggest_500').and_return(false)
      allow(described_class).to receive(:fire_probe)

      described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500').join

      expect(described_class).not_to have_received(:fire_probe)
      expect(redis).to have_received(:close)
      expect(Rails.logger).to have_received(:info).with(/after 0 iterations/)
    end

    it 'fires a batch of probes per iteration while the key exists' do
      allow(redis).to receive(:exists?).and_return(true, false)
      allow(described_class).to receive(:fire_probe)
      allow(described_class).to receive(:sleep)

      described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500').join

      expect(described_class).to have_received(:fire_probe).exactly(described_class::PROBE_BATCH).times
      expect(described_class).to have_received(:sleep).with(described_class::PROBE_INTERVAL)
      expect(Rails.logger).to have_received(:info).with(/after 1 iterations/)
    end

    it 'logs and closes redis when the probe loop raises' do
      allow(redis).to receive(:exists?).and_raise(Redis::CannotConnectError, 'gone')

      described_class.start(service: 'file-service', redis_key: 'chaos:file-service:upload_s3_error').join

      expect(Rails.logger).to have_received(:error).with(/Thread error for file-service/)
      expect(redis).to have_received(:close)
    end
  end

  describe '.fire_probe' do
    it 'issues a GET with the configured headers' do
      described_class.fire_probe(described_class::SERVICE_PROBES['search-service'])

      expect(Net::HTTP).to have_received(:new).with('search-service', 8087)
      expect(http).to have_received(:request) do |request|
        expect(request).to be_a(Net::HTTP::Get)
        expect(request['X-User-ID']).to eq('chaos-probe')
      end
    end

    it 'honours a custom read timeout' do
      described_class.fire_probe(described_class::SERVICE_PROBES['document-service'])

      expect(http).to have_received(:read_timeout=).with(8)
    end

    it 'builds a multipart upload for file-service' do
      described_class.fire_probe(described_class::SERVICE_PROBES['file-service'])

      expect(http).to have_received(:request) do |request|
        expect(request['Content-Type']).to match(%r{\Amultipart/form-data; boundary=chaos-probe-})
        expect(request.body).to include('filename="probe.txt"', 'chaos probe')
      end
    end

    it 'builds an SQS SendMessage form for notification-service' do
      described_class.fire_probe(described_class::SERVICE_PROBES['notification-service'])

      expect(http).to have_received(:request) do |request|
        expect(request['Content-Type']).to eq('application/x-www-form-urlencoded')
        params = URI.decode_www_form(request.body).to_h
        expect(params['Action']).to eq('SendMessage')
        expect(JSON.parse(params['MessageBody'])['timestamp']).to be_a(Integer)
      end
    end

    it 'builds a plain POST with an optional body' do
      described_class.fire_probe(url: 'http://example.test/probe', method: :post, body: 'payload', headers: nil)

      expect(http).to have_received(:request) do |request|
        expect(request).to be_a(Net::HTTP::Post)
        expect(request.body).to eq('payload')
      end
    end

    it 'swallows connection errors' do
      allow(http).to receive(:request).and_raise(Errno::ECONNREFUSED)

      expect(described_class.fire_probe(described_class::SERVICE_PROBES['search-service'])).to be_nil
    end
  end
end
