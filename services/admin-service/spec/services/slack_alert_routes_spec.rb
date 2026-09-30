require 'rails_helper'

RSpec.describe SlackAlertRoutes do
  after { described_class.reset! }

  it 'routes known alert names to the default channel' do
    expect(described_class.channel_for('FileUploadFailed')).to eq('#automated-alerts')
  end

  it 'routes unknown alert names to the default channel' do
    expect(described_class.channel_for('BrandNewChaosError')).to eq('#automated-alerts')
  end

  it 'routes DocumentCreateFailed to #eng-otterworks for the Devin Slack listener' do
    expect(described_class.channel_for('DocumentCreateFailed')).to eq('#eng-otterworks')
    expect(described_class.slack_listener?('DocumentCreateFailed')).to be(true)
  end

  it 'leaves other alerts on the API-created Devin session path' do
    expect(described_class.slack_listener?('FileUploadFailed')).to be(false)
    expect(described_class.slack_listener?('BrandNewChaosError')).to be(false)
  end

  it 'honors a per-alert channel override' do
    allow(YAML).to receive(:safe_load_file).and_return(
      'default' => { 'channel' => '#automated-alerts' },
      'alerts' => { 'DbChaos' => { 'channel' => '#db-alerts' } }
    )
    described_class.reset!

    expect(described_class.channel_for('DbChaos')).to eq('#db-alerts')
    expect(described_class.channel_for('OtherChaos')).to eq('#automated-alerts')
  end

  it 'falls back to the default channel when sections are empty or malformed' do
    allow(YAML).to receive(:safe_load_file).and_return(
      'default' => nil,
      'alerts' => nil
    )
    described_class.reset!

    expect(described_class.channel_for('Anything')).to eq('#automated-alerts')

    allow(YAML).to receive(:safe_load_file).and_return(
      'default' => { 'channel' => '#automated-alerts' },
      'alerts' => { 'DbChaos' => '#db-alerts' }
    )
    described_class.reset!

    expect(described_class.channel_for('DbChaos')).to eq('#automated-alerts')
  end

  it 'falls back to the hardcoded channel when the config is unreadable' do
    allow(YAML).to receive(:safe_load_file).and_raise(Errno::ENOENT)
    described_class.reset!

    expect(described_class.channel_for('Anything')).to eq('#automated-alerts')
  end
end
