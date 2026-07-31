require 'rails_helper'

RSpec.describe ChaosProbeService do
  let(:redis) { instance_double(Redis, close: nil) }
  let(:http) { instance_double(Net::HTTP, :open_timeout= => nil, :read_timeout= => nil) }

  describe '.start' do
    before do
      allow(Redis).to receive(:new).and_return(redis)
      allow(described_class).to receive(:sleep)
    end

    it 'returns nil without spawning a thread for an unknown service' do
      expect(described_class.start(service: 'nope-service', redis_key: 'chaos:nope')).to be_nil
      expect(Redis).not_to have_received(:new)
    end

    it 'probes in batches while the chaos key exists and stops once it expires' do
      allow(redis).to receive(:exists?).with('chaos:search-service:suggest_500').and_return(true, true, false)
      allow(described_class).to receive(:fire_probe)

      described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500').join(10)

      expect(described_class).to have_received(:fire_probe)
        .with(described_class::SERVICE_PROBES['search-service'])
        .exactly(described_class::PROBE_BATCH * 2).times
      expect(described_class).to have_received(:sleep).with(described_class::PROBE_INTERVAL).twice
      expect(redis).to have_received(:close)
    end

    it 'logs without closing anything when the redis client cannot be built' do
      allow(Redis).to receive(:new).and_raise(Redis::CannotConnectError, 'no route')
      allow(Rails.logger).to receive(:error)

      described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500').join(10)

      expect(Rails.logger).to have_received(:error).with(/Thread error for search-service/)
    end

    it 'logs and closes redis when the probe loop raises' do
      allow(redis).to receive(:exists?).and_raise(Redis::CannotConnectError, 'refused')
      allow(Rails.logger).to receive(:error)

      described_class.start(service: 'file-service', redis_key: 'chaos:file-service:upload_s3_error').join(10)

      expect(Rails.logger).to have_received(:error).with(/\[ChaosProbe\] Thread error for file-service/)
      expect(redis).to have_received(:close)
    end
  end

  describe '.fire_probe' do
    before { allow(Net::HTTP).to receive(:new).and_return(http) }

    it 'issues a GET with the configured headers for a plain probe' do
      captured = nil
      allow(http).to receive(:request) { |req| captured = req }

      described_class.fire_probe(described_class::SERVICE_PROBES['search-service'])

      expect(Net::HTTP).to have_received(:new).with('search-service', 8087)
      expect(captured).to be_a(Net::HTTP::Get)
      expect(captured.path).to eq('/api/v1/search/suggest?q=test')
      expect(captured['X-User-ID']).to eq('chaos-probe')
    end

    it 'honours a per-probe read timeout' do
      allow(http).to receive(:request)

      described_class.fire_probe(described_class::SERVICE_PROBES['document-service'])

      expect(http).to have_received(:read_timeout=).with(8)
    end

    it 'builds a multipart upload for the file-service probe' do
      captured = nil
      allow(http).to receive(:request) { |req| captured = req }

      described_class.fire_probe(described_class::SERVICE_PROBES['file-service'])

      expect(captured).to be_a(Net::HTTP::Post)
      expect(captured['Content-Type']).to match(%r{\Amultipart/form-data; boundary=chaos-probe-\h{16}\z})
      expect(captured.body).to include('name="file"; filename="probe.txt"', 'chaos probe')
      expect(captured['X-User-ID']).to eq('00000000-0000-0000-0000-000000000001')
    end

    it 'builds an SQS SendMessage with an integer timestamp for notification-service' do
      captured = nil
      allow(http).to receive(:request) { |req| captured = req }

      described_class.fire_probe(described_class::SERVICE_PROBES['notification-service'])

      expect(captured['Content-Type']).to eq('application/x-www-form-urlencoded')
      form = URI.decode_www_form(captured.body).to_h
      expect(form['Action']).to eq('SendMessage')
      expect(JSON.parse(form['MessageBody'])).to include('eventType' => 'file_shared')
      expect(JSON.parse(form['MessageBody'])['timestamp']).to be_an(Integer)
    end

    it 'builds a plain POST with a body when the probe declares one' do
      captured = nil
      allow(http).to receive(:request) { |req| captured = req }

      described_class.fire_probe({ url: 'http://svc:8080/ping', method: :post, body: 'payload' })

      expect(captured).to be_a(Net::HTTP::Post)
      expect(captured.body).to eq('payload')
    end

    it 'builds a bodyless POST when the probe declares no body' do
      captured = nil
      allow(http).to receive(:request) { |req| captured = req }

      described_class.fire_probe({ url: 'http://svc:8080/ping', method: :post })

      expect(captured).to be_a(Net::HTTP::Post)
      expect(captured.body).to be_nil
    end

    it 'swallows transport errors' do
      allow(http).to receive(:request).and_raise(Errno::ECONNREFUSED)

      expect(described_class.fire_probe(described_class::SERVICE_PROBES['search-service'])).to be_nil
    end
  end
end
