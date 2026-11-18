require 'rails_helper'

RSpec.describe ChaosProbeService do
  describe '.start' do
    let(:redis) { instance_double(Redis, close: nil) }

    before do
      allow(Redis).to receive(:new).and_return(redis)
      allow(Thread).to receive(:new).and_yield
      allow(described_class).to receive(:sleep)
      allow(described_class).to receive(:fire_probe)
    end

    it 'does nothing for a service without a probe' do
      expect(described_class.start(service: 'auth-service', redis_key: 'k')).to be_nil
      expect(Thread).not_to have_received(:new)
    end

    it 'fires probe batches until the chaos key expires' do
      allow(redis).to receive(:exists?).with('chaos:search-service:suggest_500').and_return(true, true, false)

      described_class.start(service: 'search-service', redis_key: 'chaos:search-service:suggest_500')

      expect(described_class).to have_received(:fire_probe)
        .with(described_class::SERVICE_PROBES['search-service']).exactly(2 * described_class::PROBE_BATCH).times
      expect(described_class).to have_received(:sleep).with(described_class::PROBE_INTERVAL).twice
      expect(redis).to have_received(:close)
    end

    it 'logs and closes Redis when the loop raises' do
      allow(redis).to receive(:exists?).and_raise(Redis::CannotConnectError, 'down')
      allow(Rails.logger).to receive(:error)

      described_class.start(service: 'file-service', redis_key: 'k')

      expect(Rails.logger).to have_received(:error).with(/Thread error for file-service: Redis::CannotConnectError - down/)
      expect(redis).to have_received(:close)
    end
  end

  describe '.fire_probe' do
    let(:http) { instance_double(Net::HTTP, :open_timeout= => nil, :read_timeout= => nil) }
    let(:sent) { [] }

    before do
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:request) { |req| sent << req; :response }
    end

    it 'sends a GET with configured headers by default' do
      expect(described_class.fire_probe(described_class::SERVICE_PROBES['search-service'])).to eq(:response)
      expect(Net::HTTP).to have_received(:new).with('search-service', 8087)
      expect(http).to have_received(:read_timeout=).with(3)
      expect(sent.first).to be_a(Net::HTTP::Get)
      expect(sent.first.path).to eq('/api/v1/search/suggest?q=test')
      expect(sent.first['X-User-ID']).to eq('chaos-probe')
    end

    it 'honours a custom read timeout' do
      described_class.fire_probe(described_class::SERVICE_PROBES['document-service'])
      expect(http).to have_received(:read_timeout=).with(8)
    end

    it 'sends a multipart upload for file-service' do
      described_class.fire_probe(described_class::SERVICE_PROBES['file-service'])
      req = sent.first
      expect(req).to be_a(Net::HTTP::Post)
      expect(req['Content-Type']).to match(%r{\Amultipart/form-data; boundary=chaos-probe-\h{16}\z})
      expect(req.body).to include('name="file"; filename="probe.txt"', 'chaos probe')
      expect(req['X-User-ID']).to eq('00000000-0000-0000-0000-000000000001')
    end

    it 'sends an SQS SendMessage with an integer timestamp for notification-service' do
      described_class.fire_probe(described_class::SERVICE_PROBES['notification-service'])
      req = sent.first
      expect(req['Content-Type']).to eq('application/x-www-form-urlencoded')
      form = URI.decode_www_form(req.body).to_h
      expect(form).to include('Action' => 'SendMessage', 'Version' => '2012-11-05')
      expect(JSON.parse(form['MessageBody'])).to include('eventType' => 'file_shared', 'timestamp' => a_kind_of(Integer))
    end

    it 'supports plain POST probes with and without a body' do
      described_class.fire_probe(url: 'http://x:1/p', method: :post, body: 'payload')
      described_class.fire_probe(url: 'http://x:1/p', method: :post)
      expect(sent.map(&:class)).to eq([Net::HTTP::Post, Net::HTTP::Post])
      expect(sent.map(&:body)).to eq(['payload', nil])
    end

    it 'tolerates a config without headers' do
      described_class.fire_probe(url: 'http://x:1/p')
      expect(sent.first).to be_a(Net::HTTP::Get)
    end

    it 'swallows network errors' do
      allow(http).to receive(:request).and_raise(Errno::ECONNREFUSED)
      expect(described_class.fire_probe(described_class::SERVICE_PROBES['search-service'])).to be_nil
    end
  end
end
