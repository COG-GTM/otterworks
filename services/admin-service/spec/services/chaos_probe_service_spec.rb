require 'rails_helper'

RSpec.describe ChaosProbeService do
  describe 'SERVICE_PROBES' do
    it 'sends the probe user id under the X-User-ID header' do
      expect(described_class::USER_ID_HEADER).to eq('X-User-ID')
      expect(described_class::SERVICE_PROBES['search-service'][:headers]).to eq('X-User-ID' => 'chaos-probe')
      %w[file-service document-service].each do |service|
        expect(described_class::SERVICE_PROBES[service][:headers])
          .to eq('X-User-ID' => '00000000-0000-0000-0000-000000000001')
      end
    end
  end

  describe '.fire_probe' do
    it 'applies the configured headers to the outgoing request' do
      sent = nil
      http = instance_double(Net::HTTP, :open_timeout= => nil, :read_timeout= => nil)
      allow(http).to receive(:request) { |req| sent = req }
      allow(Net::HTTP).to receive(:new).with('document-service', 8083).and_return(http)

      described_class.fire_probe(described_class::SERVICE_PROBES['document-service'])

      expect(sent).to be_a(Net::HTTP::Get)
      expect(sent['X-User-ID']).to eq('00000000-0000-0000-0000-000000000001')
    end
  end
end
