require 'rails_helper'

RSpec.describe SlackNotifierService do
  let(:incident) do
    Incident.create!(
      title: 'FileUploadFailed: report.pdf',
      description: 'S3 PutObject failed with AccessDenied',
      severity: 'critical',
      affected_service: 'file-service',
      status: 'investigating'
    )
  end

  before do
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil).and_return(nil)
    allow(ENV).to receive(:fetch).with('SLACK_BOT_TOKEN', nil).and_return(nil)
    allow(ENV).to receive(:fetch).with('SLACK_ONCALL_MEMBER', nil).and_return(nil)
    allow(ENV).to receive(:fetch).with('SLACK_USER_MAP', nil).and_return(nil)
    allow(AdminSettingsService).to receive(:slack_notifications_enabled?).and_return(true)
    allow(AdminSettingsService).to receive(:slack_webhook_url).and_return(nil)
  end

  def stub_post(response_body: '{"ok":true}')
    posted = nil
    posted_req = nil
    http = instance_double(Net::HTTP)
    allow(Net::HTTP).to receive(:new).and_return(http)
    allow(http).to receive(:use_ssl=)
    allow(http).to receive(:open_timeout=)
    allow(http).to receive(:read_timeout=)
    allow(http).to receive(:request) do |req|
      posted = JSON.parse(req.body)
      posted_req = req
      instance_double(Net::HTTPOK).tap do |r|
        allow(r).to receive(:is_a?).with(Net::HTTPSuccess).and_return(true)
        allow(r).to receive(:body).and_return(response_body)
      end
    end
    [-> { posted }, -> { posted_req }]
  end

  it 'does nothing when no webhook is configured anywhere' do
    expect(Net::HTTP).not_to receive(:new)
    described_class.notify_incident(incident: incident)
  end

  it 'does nothing when notifications are disabled' do
    allow(AdminSettingsService).to receive(:slack_notifications_enabled?).and_return(false)
    expect(Net::HTTP).not_to receive(:new)
    described_class.notify_incident(incident: incident)
  end

  it 'posts to chat.postMessage with the routed channel when SLACK_BOT_TOKEN is set' do
    allow(ENV).to receive(:fetch).with('SLACK_BOT_TOKEN', nil).and_return('xoxb-test-token')
    read_posted, read_request = stub_post

    described_class.notify_incident(incident: incident, alert_name: 'FileUploadFailed')

    expect(Net::HTTP).to have_received(:new).with('slack.com', 443)
    expect(read_request.call['Authorization']).to eq('Bearer xoxb-test-token')
    expect(read_posted.call['channel']).to eq('#automated-alerts')
    expect(read_posted.call['blocks']).to be_an(Array)
  end

  it 'routes unknown alert names to the default channel' do
    allow(ENV).to receive(:fetch).with('SLACK_BOT_TOKEN', nil).and_return('xoxb-test-token')
    read_posted, = stub_post

    described_class.notify_incident(incident: incident, alert_name: 'SomeBrandNewChaosError')

    expect(read_posted.call['channel']).to eq('#automated-alerts')
  end

  it 'prefers the bot token over a configured webhook' do
    allow(ENV).to receive(:fetch).with('SLACK_BOT_TOKEN', nil).and_return('xoxb-test-token')
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    _, read_request = stub_post

    described_class.notify_incident(incident: incident)

    expect(read_request.call.uri.to_s).to eq('https://slack.com/api/chat.postMessage')
  end

  it 'posts the alert-format message with the Devin session link' do
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    read_posted, = stub_post

    described_class.notify_incident(
      incident: incident,
      session_url: 'https://app.devin.ai/sessions/abc',
      reporter_email: 'preston@example.com'
    )

    posted = read_posted.call
    header = posted['blocks'][0]['text']['text']
    body   = posted['blocks'][1]['text']['text']
    footer = posted['blocks'][2]['elements'][0]['text']

    expect(header).to eq('OtterWorks Alert — file-service — FileUploadFailed: report.pdf')
    expect(body).to include('*Error:*', 'FileUploadFailed: report.pdf')
    expect(body).to include('*Severity:*', 'critical')
    expect(body).to include('*Type:*', 'FileUploadFailed')
    expect(body).to include('*Message:*', 'S3 PutObject failed with AccessDenied')
    expect(body).to include('<https://app.devin.ai/sessions/abc|Devin AI (auto-investigating)>')
    expect(body).to include('preston@example.com')
    expect(footer).to start_with('Service: file-service | ')
  end

  it 'truncates long titles so Slack does not reject the message' do
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    incident.update!(title: "BigFailure: #{'x' * 240}", description: 'y' * 5000)
    read_posted, = stub_post

    described_class.notify_incident(incident: incident, session_url: 'https://app.devin.ai/sessions/abc')

    posted = read_posted.call
    expect(posted['blocks'][0]['text']['text'].length).to be <= 150
    expect(posted['blocks'][1]['text']['text'].length).to be <= 3000
    expect(posted['blocks'][1]['text']['text'])
      .to include('<https://app.devin.ai/sessions/abc|Devin AI (auto-investigating)>')
  end

  it 'renders a true mention when the reporter is in SLACK_USER_MAP' do
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    allow(ENV).to receive(:fetch).with('SLACK_USER_MAP', nil)
      .and_return({ 'preston@example.com' => 'U08S7AVJ478' }.to_json)
    read_posted, = stub_post

    described_class.notify_incident(incident: incident, reporter_email: 'preston@example.com')

    expect(read_posted.call['blocks'][1]['text']['text']).to include('<@U08S7AVJ478>')
  end

  it 'falls back to the settings-stored webhook when the env var is absent' do
    allow(AdminSettingsService).to receive(:slack_webhook_url)
      .and_return('https://hooks.slack.com/services/T/B/stored')
    read_posted, = stub_post

    described_class.notify_incident(incident: incident)

    expect(read_posted.call).not_to be_nil
  end

  it 'ignores a stored webhook that is not a hooks.slack.com HTTPS URL' do
    allow(AdminSettingsService).to receive(:slack_webhook_url)
      .and_return('http://169.254.169.254/latest')
    read_posted, = stub_post

    described_class.notify_incident(incident: incident)

    expect(read_posted.call).to be_nil
  end

  it 'swallows network errors' do
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    allow(Net::HTTP).to receive(:new).and_raise(SocketError, 'boom')

    expect { described_class.notify_incident(incident: incident) }.not_to raise_error
  end
end
