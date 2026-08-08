require 'rails_helper'

RSpec.describe ChaosProbeService do
  let(:redis) { instance_double(Redis, close: nil) }
  let(:http) { instance_double(Net::HTTP, :open_timeout= => nil, :read_timeout= => nil, request: nil) }

  describe '.start' do
    before do
      allow(Redis).to receive(:new).and_return(redis)
      allow(described_class).to receive(:sleep)
      allow(described_class).to receive(:fire_probe)
    end

    it 'does nothing for a service without a probe configuration' do
      expect(described_class.start(service: 'audit-service', redis_key: 'chaos:audit-service:x')).to be_nil
      expect(Redis).not_to have_received(:new)
    end

    it 'stops immediately when the chaos key is already gone' do
      allow(redis).to receive(:exists?).with('chaos:search-service:suggest_500').and_return(false)

      described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500').join

      expect(described_class).not_to have_received(:fire_probe)
      expect(redis).to have_received(:close)
    end

    it 'fires a batch of probes per iteration while the chaos key exists' do
      allow(redis).to receive(:exists?).and_return(true, true, false)

      described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500').join

      expect(described_class).to have_received(:fire_probe)
        .with(described_class::SERVICE_PROBES['search-service'])
        .exactly(described_class::PROBE_BATCH * 2).times
      expect(described_class).to have_received(:sleep).with(described_class::PROBE_INTERVAL).twice
    end

    it 'logs and gives up when the redis connection cannot be built' do
      allow(Rails.logger).to receive(:info)
      allow(Rails.logger).to receive(:error)
      allow(Redis).to receive(:new).and_raise(Redis::CannotConnectError, 'no route')

      described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500').join

      expect(Rails.logger).to have_received(:error).with(/Thread error for search-service/)
      expect(described_class).not_to have_received(:fire_probe)
    end

    it 'logs and closes redis when the probe loop raises' do
      allow(Rails.logger).to receive(:info)
      allow(Rails.logger).to receive(:error)
      allow(redis).to receive(:exists?).and_raise(Redis::CannotConnectError, 'gone')

      described_class.start(service: 'file-service', redis_key: 'chaos:file-service:upload_s3_error').join

      expect(Rails.logger).to have_received(:error).with(/Thread error for file-service/)
      expect(redis).to have_received(:close)
    end
  end

  describe '.fire_probe' do
    before { allow(Net::HTTP).to receive(:new).and_return(http) }

    it 'issues a GET with the configured headers by default' do
      config = described_class::SERVICE_PROBES['search-service']
      captured = nil
      allow(http).to receive(:request) { |request| captured = request }

      described_class.fire_probe(config)

      expect(captured).to be_a(Net::HTTP::Get)
      expect(captured.path).to eq('/api/v1/search/suggest?q=test')
      expect(captured['X-User-ID']).to eq('chaos-probe')
    end

    it 'builds a multipart upload for the file-service probe' do
      captured = nil
      allow(http).to receive(:request) { |request| captured = request }

      described_class.fire_probe(described_class::SERVICE_PROBES['file-service'])

      expect(captured).to be_a(Net::HTTP::Post)
      expect(captured['Content-Type']).to start_with('multipart/form-data; boundary=chaos-probe-')
      expect(captured.body).to include('filename="probe.txt"', 'chaos probe')
    end

    it 'builds an SQS SendMessage form post for the notification-service probe' do
      captured = nil
      allow(http).to receive(:request) { |request| captured = request }

      described_class.fire_probe(described_class::SERVICE_PROBES['notification-service'])

      expect(captured['Content-Type']).to eq('application/x-www-form-urlencoded')
      form = URI.decode_www_form(captured.body).to_h
      expect(form['Action']).to eq('SendMessage')
      expect(JSON.parse(form['MessageBody'])['timestamp']).to be_a(Integer)
    end

    it 'honours a custom read timeout' do
      described_class.fire_probe(described_class::SERVICE_PROBES['document-service'])

      expect(http).to have_received(:read_timeout=).with(8)
    end

    it 'builds a plain POST with a body when the method is :post' do
      captured = nil
      allow(http).to receive(:request) { |request| captured = request }

      described_class.fire_probe(url: 'http://example.test/probe', method: :post, body: 'ping', headers: nil)

      expect(captured).to be_a(Net::HTTP::Post)
      expect(captured.body).to eq('ping')
    end

    it 'builds a bodyless POST when the method is :post without a body' do
      captured = nil
      allow(http).to receive(:request) { |request| captured = request }

      described_class.fire_probe(url: 'http://example.test/probe', method: :post, headers: {})

      expect(captured).to be_a(Net::HTTP::Post)
      expect(captured.body).to be_nil
    end

    it 'swallows transport errors' do
      allow(http).to receive(:request).and_raise(Errno::ECONNREFUSED)

      expect(described_class.fire_probe(described_class::SERVICE_PROBES['search-service'])).to be_nil
    end
  end
end
