require 'rails_helper'

RSpec.describe ChaosProbeService do
  let(:redis) { instance_double(Redis, close: nil) }
  let(:http) { instance_double(Net::HTTP, :open_timeout= => nil, :read_timeout= => nil, request: nil) }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(described_class).to receive(:sleep)
  end

  describe '.start' do
    it 'does nothing for an unknown service' do
      expect(described_class.start(service: 'unknown-service', redis_key: 'chaos:x')).to be_nil
      expect(Redis).not_to have_received(:new)
    end

    it 'stops immediately when the chaos key is already gone' do
      allow(redis).to receive(:exists?).with('chaos:search-service:suggest_500').and_return(false)
      allow(described_class).to receive(:fire_probe)

      described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500').join

      expect(described_class).not_to have_received(:fire_probe)
      expect(redis).to have_received(:close)
    end

    it 'fires a batch of probes per iteration while the chaos key lives' do
      allow(redis).to receive(:exists?).and_return(true, true, false)
      allow(described_class).to receive(:fire_probe)

      described_class.start(service: 'file-service', redis_key: 'chaos:file-service:upload_s3_error').join

      expect(described_class).to have_received(:fire_probe).exactly(described_class::PROBE_BATCH * 2).times
      expect(described_class).to have_received(:sleep).with(described_class::PROBE_INTERVAL).twice
    end

    it 'logs and closes redis when the probe loop raises' do
      allow(redis).to receive(:exists?).and_raise(Redis::BaseConnectionError, 'gone')
      allow(Rails.logger).to receive(:error)

      described_class.start(service: 'document-service', redis_key: 'chaos:document-service:slow_queries').join

      expect(Rails.logger).to have_received(:error).with(/Thread error for document-service/)
      expect(redis).to have_received(:close)
    end
  end

  describe '.fire_probe' do
    before { allow(Net::HTTP).to receive(:new).and_return(http) }

    it 'issues a GET with the configured headers' do
      described_class.fire_probe(described_class::SERVICE_PROBES['search-service'])

      expect(Net::HTTP).to have_received(:new).with('search-service', 8087)
      expect(http).to have_received(:request) do |req|
        expect(req).to be_a(Net::HTTP::Get)
        expect(req['X-User-ID']).to eq('chaos-probe')
        expect(req.path).to eq('/api/v1/search/suggest?q=test')
      end
    end

    it 'issues a multipart POST carrying a dummy file' do
      described_class.fire_probe(described_class::SERVICE_PROBES['file-service'])

      expect(http).to have_received(:request) do |req|
        expect(req).to be_a(Net::HTTP::Post)
        expect(req['Content-Type']).to match(%r{\Amultipart/form-data; boundary=chaos-probe-})
        expect(req.body).to include('filename="probe.txt"', 'chaos probe')
      end
    end

    it 'issues an SQS SendMessage POST with an integer timestamp' do
      described_class.fire_probe(described_class::SERVICE_PROBES['notification-service'])

      expect(http).to have_received(:request) do |req|
        expect(req['Content-Type']).to eq('application/x-www-form-urlencoded')
        form = URI.decode_www_form(req.body).to_h
        expect(form['Action']).to eq('SendMessage')
        message = JSON.parse(form['MessageBody'])
        expect(message['eventType']).to eq('file_shared')
        expect(message['timestamp']).to be_a(Integer)
      end
    end

    it 'issues a plain POST with the configured body' do
      described_class.fire_probe(url: 'http://svc:8080/probe', method: :post, body: 'payload', headers: nil)

      expect(http).to have_received(:request) do |req|
        expect(req).to be_a(Net::HTTP::Post)
        expect(req.body).to eq('payload')
      end
    end

    it 'honours the per-service read timeout' do
      described_class.fire_probe(described_class::SERVICE_PROBES['document-service'])

      expect(http).to have_received(:read_timeout=).with(8)
    end

    it 'swallows transport errors' do
      allow(http).to receive(:request).and_raise(Errno::ECONNREFUSED)

      expect(described_class.fire_probe(described_class::SERVICE_PROBES['search-service'])).to be_nil
    end
  end
end
