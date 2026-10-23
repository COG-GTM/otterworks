require 'rails_helper'

RSpec.describe ChaosProbeService do
  let(:redis) { instance_double(Redis, close: nil) }
  let(:active_keys) { Set.new(%w[chaos:file-service:upload_s3_error chaos:search-service:suggest_500]) }
  let(:started) { [] }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(redis).to receive(:exists?) { |key| active_keys.include?(key) }
    allow(described_class).to receive(:fire_probe)
    allow(described_class).to receive(:sleep) { Kernel.sleep(0.01) }
  end

  after do
    active_keys.clear
    started.compact.each { |thread| thread.join(2) }
  end

  def start(service, key)
    described_class.start(service: service, redis_key: key).tap { |thread| started << thread }
  end

  it 'ignores services without a probe' do
    expect(start('auth-service', 'chaos:auth-service:x')).to be_nil
  end

  it 'reuses the running probe when the same key is re-triggered' do
    first = start('file-service', 'chaos:file-service:upload_s3_error')
    5.times { expect(start('file-service', 'chaos:file-service:upload_s3_error')).to equal(first) }
    expect(Redis).to have_received(:new).once
    expect(described_class.running?('chaos:file-service:upload_s3_error')).to be(true)
  end

  it 'runs independent probes for different keys' do
    file_probe = start('file-service', 'chaos:file-service:upload_s3_error')
    search_probe = start('search-service', 'chaos:search-service:suggest_500')
    expect(search_probe).not_to equal(file_probe)
  end

  it 'starts a fresh probe once the previous one has exited' do
    first = start('file-service', 'chaos:file-service:upload_s3_error')
    active_keys.delete('chaos:file-service:upload_s3_error')
    expect(first.join(2)).to equal(first)
    expect(described_class.running?('chaos:file-service:upload_s3_error')).to be(false)

    active_keys << 'chaos:file-service:upload_s3_error'
    second = start('file-service', 'chaos:file-service:upload_s3_error')
    expect(second).not_to equal(first)
    expect(second).to be_alive
  end
end
