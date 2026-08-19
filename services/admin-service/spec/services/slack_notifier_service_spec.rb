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
    allow(AdminSettingsService).to receive(:slack_bot_token).and_return(nil)
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

  it 'uses the runtime-stored bot token when SLACK_BOT_TOKEN is not set' do
    allow(AdminSettingsService).to receive(:slack_bot_token).and_return('xoxb-stored-token')
    read_posted, read_request = stub_post

    described_class.notify_incident(incident: incident, alert_name: 'FileUploadFailed')

    expect(Net::HTTP).to have_received(:new).with('slack.com', 443)
    expect(read_request.call['Authorization']).to eq('Bearer xoxb-stored-token')
    expect(read_posted.call['channel']).to eq('#automated-alerts')
  end

  it 'ignores a malformed stored token and falls back to the webhook' do
    allow(AdminSettingsService).to receive(:slack_bot_token).and_return("garbage\r\nvalue")
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    _, read_request = stub_post

    described_class.notify_incident(incident: incident, alert_name: 'FileUploadFailed')

    expect(Net::HTTP).to have_received(:new).with('hooks.slack.com', 443)
    expect(read_request.call['Authorization']).to be_nil
  end

  it 'falls back to the webhook when chat.postMessage rejects the token' do
    allow(ENV).to receive(:fetch).with('SLACK_BOT_TOKEN', nil).and_return('xoxb-revoked')
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    requests = []
    http = instance_double(Net::HTTP)
    allow(Net::HTTP).to receive(:new).and_return(http)
    allow(http).to receive(:use_ssl=)
    allow(http).to receive(:open_timeout=)
    allow(http).to receive(:read_timeout=)
    allow(http).to receive(:request) do |req|
      requests << req
      body = req.uri.host == 'slack.com' ? '{"ok":false,"error":"invalid_auth"}' : '{"ok":true}'
      instance_double(Net::HTTPOK).tap do |r|
        allow(r).to receive(:is_a?).with(Net::HTTPSuccess).and_return(true)
        allow(r).to receive(:body).and_return(body)
      end
    end

    described_class.notify_incident(incident: incident, alert_name: 'FileUploadFailed')

    expect(requests.map { |r| r.uri.host }).to eq(%w[slack.com hooks.slack.com])
    expect(requests.last['Authorization']).to be_nil
  end

  it 'falls back to the webhook when the Slack API is unreachable' do
    allow(ENV).to receive(:fetch).with('SLACK_BOT_TOKEN', nil).and_return('xoxb-test-token')
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    requests = []
    http = instance_double(Net::HTTP)
    allow(Net::HTTP).to receive(:new).and_return(http)
    allow(http).to receive(:use_ssl=)
    allow(http).to receive(:open_timeout=)
    allow(http).to receive(:read_timeout=)
    allow(http).to receive(:request) do |req|
      requests << req
      raise Net::OpenTimeout, 'execution expired' if req.uri.host == 'slack.com'

      instance_double(Net::HTTPOK).tap do |r|
        allow(r).to receive(:is_a?).with(Net::HTTPSuccess).and_return(true)
        allow(r).to receive(:body).and_return('ok')
      end
    end

    described_class.notify_incident(incident: incident, alert_name: 'FileUploadFailed')

    expect(requests.map { |r| r.uri.host }).to eq(%w[slack.com hooks.slack.com])
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
    blocks = posted['blocks']
    header = blocks[0]['text']['text']
    fields = blocks.select { |b| b['fields'] }.flat_map { |b| b['fields'].map { |f| f['text'] } }
    message = blocks[3]['text']['text']
    footer = blocks.last['elements'][0]['text']

    expect(header).to eq(':rotating_light: OtterWorks Alert — file-service — FileUploadFailed: report.pdf')
    expect(fields).to include("*Error:*\nFileUploadFailed: report.pdf")
    expect(fields).to include("*Severity:*\ncritical")
    expect(fields).to include("*Location:*\n`file-service`")
    expect(fields).to include("*Type:*\nFileUploadFailed")
    expect(message).to eq("*Message:*\n```S3 PutObject failed with AccessDenied```")
    expect(fields).to include("*Environment:*\ntest")
    expect(fields).to include("*On-Call:*\n:robot_face: <https://app.devin.ai/sessions/abc|Devin AI (auto-investigating)>")
    expect(fields).to include("*On-Call:*\npreston@example.com")
    expect(footer).to start_with('Service: `file-service` | ')
  end

  it 'escapes Slack control sequences in the description so alert text cannot inject mentions or links' do
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    incident.update!(description: 'boom <!channel> & <https://evil.example|click>')
    read_posted, = stub_post

    described_class.notify_incident(incident: incident, session_url: nil)

    message = read_posted.call['blocks'][3]['text']['text']
    expect(message).to eq(
      "*Message:*\n```boom &lt;!channel&gt; &amp; &lt;https://evil.example|click&gt;```"
    )
  end

  it 'drops a trailing partial entity when truncation cuts the escaped description' do
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    # SECTION_MAX(3000) - "*Message:*\n``````".length(17) = 2983; truncate
    # keeps 2982 chars + "…", so "&lt;" starting at index 2980 is cut to "&l".
    incident.update!(description: "#{'x' * 2980}<oops long tail")
    read_posted, = stub_post

    described_class.notify_incident(incident: incident, session_url: nil)

    message = read_posted.call['blocks'][3]['text']['text']
    expect(message).to end_with("x\u2026```")
    expect(message.length).to be <= 3000
  end

  it 'truncates long titles so Slack does not reject the message' do
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    incident.update!(title: "BigFailure: #{'x' * 240}", description: 'y' * 5000)
    read_posted, = stub_post

    described_class.notify_incident(incident: incident, session_url: 'https://app.devin.ai/sessions/abc')

    posted = read_posted.call
    expect(posted['blocks'][0]['text']['text'].length).to be <= 150
    expect(posted['blocks'][3]['text']['text'].length).to be <= 3000
    fields = posted['blocks'].select { |b| b['fields'] }.flat_map { |b| b['fields'].map { |f| f['text'] } }
    expect(fields.map(&:length)).to all(be <= 2000)
    expect(fields)
      .to include("*On-Call:*\n:robot_face: <https://app.devin.ai/sessions/abc|Devin AI (auto-investigating)>")
  end

  it 'renders a true mention when the reporter is in SLACK_USER_MAP' do
    allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
      .and_return('https://hooks.slack.com/services/T/B/x')
    allow(ENV).to receive(:fetch).with('SLACK_USER_MAP', nil)
      .and_return({ 'preston@example.com' => 'U08S7AVJ478' }.to_json)
    read_posted, = stub_post

    described_class.notify_incident(incident: incident, reporter_email: 'preston@example.com')

    fields = read_posted.call['blocks'].select { |b| b['fields'] }.flat_map { |b| b['fields'].map { |f| f['text'] } }
    expect(fields).to include("*On-Call:*\n<@U08S7AVJ478>")
  end

  describe 'dynamic Slack lookup via users.lookupByEmail' do
    def stub_slack_api(lookup_body:)
      requests = []
      posted = nil
      http = instance_double(Net::HTTP)
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:use_ssl=)
      allow(http).to receive(:open_timeout=)
      allow(http).to receive(:read_timeout=)
      allow(http).to receive(:request) do |req|
        requests << req
        body =
          if req.uri.path == '/api/users.lookupByEmail'
            lookup_body
          else
            posted = JSON.parse(req.body)
            '{"ok":true}'
          end
        instance_double(Net::HTTPOK).tap do |r|
          allow(r).to receive(:is_a?).with(Net::HTTPSuccess).and_return(true)
          allow(r).to receive(:body).and_return(body)
        end
      end
      [requests, -> { posted }]
    end

    before do
      allow(ENV).to receive(:fetch).with('SLACK_BOT_TOKEN', nil).and_return('xoxb-test-token')
    end

    it 'resolves the reporter to a true mention via users.lookupByEmail' do
      requests, read_posted = stub_slack_api(
        lookup_body: '{"ok":true,"user":{"id":"U0DYNAMIC1"}}'
      )

      described_class.notify_incident(incident: incident, reporter_email: 'preston@example.com')

      lookup = requests.find { |r| r.uri.path == '/api/users.lookupByEmail' }
      expect(lookup).not_to be_nil
      expect(lookup.uri.query).to include('email=preston%40example.com')
      expect(lookup['Authorization']).to eq('Bearer xoxb-test-token')
      fields = read_posted.call['blocks'].select { |b| b['fields'] }.flat_map { |b| b['fields'].map { |f| f['text'] } }
      expect(fields).to include("*On-Call:*\n<@U0DYNAMIC1>")
    end

    it 'falls back to the plain email when the lookup fails (e.g. missing scope)' do
      _, read_posted = stub_slack_api(
        lookup_body: '{"ok":false,"error":"missing_scope"}'
      )

      described_class.notify_incident(incident: incident, reporter_email: 'preston@example.com')

      fields = read_posted.call['blocks'].select { |b| b['fields'] }.flat_map { |b| b['fields'].map { |f| f['text'] } }
      expect(fields).to include("*On-Call:*\npreston@example.com")
    end

    it 'prefers SLACK_USER_MAP over the API lookup' do
      allow(ENV).to receive(:fetch).with('SLACK_USER_MAP', nil)
        .and_return({ 'preston@example.com' => 'U0STATIC99' }.to_json)
      requests, read_posted = stub_slack_api(
        lookup_body: '{"ok":true,"user":{"id":"U0DYNAMIC1"}}'
      )

      described_class.notify_incident(incident: incident, reporter_email: 'preston@example.com')

      expect(requests.map { |r| r.uri.path }).not_to include('/api/users.lookupByEmail')
      fields = read_posted.call['blocks'].select { |b| b['fields'] }.flat_map { |b| b['fields'].map { |f| f['text'] } }
      expect(fields).to include("*On-Call:*\n<@U0STATIC99>")
    end

    it 'still delivers the alert when the lookup raises' do
      requests = []
      posted = nil
      http = instance_double(Net::HTTP)
      allow(Net::HTTP).to receive(:new).and_return(http)
      allow(http).to receive(:use_ssl=)
      allow(http).to receive(:open_timeout=)
      allow(http).to receive(:read_timeout=)
      allow(http).to receive(:request) do |req|
        requests << req
        raise Net::OpenTimeout, 'execution expired' if req.uri.path == '/api/users.lookupByEmail'

        posted = JSON.parse(req.body)
        instance_double(Net::HTTPOK).tap do |r|
          allow(r).to receive(:is_a?).with(Net::HTTPSuccess).and_return(true)
          allow(r).to receive(:body).and_return('{"ok":true}')
        end
      end

      described_class.notify_incident(incident: incident, reporter_email: 'preston@example.com')

      fields = posted['blocks'].select { |b| b['fields'] }.flat_map { |b| b['fields'].map { |f| f['text'] } }
      expect(fields).to include("*On-Call:*\npreston@example.com")
    end

    it 'skips the lookup entirely when no bot token is configured' do
      allow(ENV).to receive(:fetch).with('SLACK_BOT_TOKEN', nil).and_return(nil)
      allow(ENV).to receive(:fetch).with('SLACK_WEBHOOK_URL', nil)
        .and_return('https://hooks.slack.com/services/T/B/x')
      read_posted, read_request = stub_post

      described_class.notify_incident(incident: incident, reporter_email: 'preston@example.com')

      expect(read_request.call.uri.host).to eq('hooks.slack.com')
      fields = read_posted.call['blocks'].select { |b| b['fields'] }.flat_map { |b| b['fields'].map { |f| f['text'] } }
      expect(fields).to include("*On-Call:*\npreston@example.com")
    end
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
