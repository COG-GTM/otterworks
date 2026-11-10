using Amazon.SQS;
using Amazon.SQS.Model;
using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Config;

namespace OtterWorks.AuditService.Services;

public class SnsConsumer : BackgroundService
{
    private readonly IAmazonSQS _sqsClient;
    private readonly IAuditRepository _repository;
    private readonly AwsSettings _settings;
    private readonly ILogger<SnsConsumer> _logger;
    private string? _queueUrl;

    public SnsConsumer(
        IAmazonSQS sqsClient,
        IAuditRepository repository,
        IOptions<AwsSettings> settings,
        ILogger<SnsConsumer> logger)
    {
        _sqsClient = sqsClient;
        _repository = repository;
        _settings = settings.Value;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("SNS Consumer starting, waiting for audit events...");

        try
        {
            _queueUrl = await GetOrCreateQueueUrlAsync(stoppingToken);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to initialize SQS queue. SNS Consumer will not process messages");
            return;
        }

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var receiveRequest = new ReceiveMessageRequest
                {
                    QueueUrl = _queueUrl,
                    MaxNumberOfMessages = 10,
                    WaitTimeSeconds = 20,
                };

                var response = await _sqsClient.ReceiveMessageAsync(receiveRequest, stoppingToken);

                foreach (var message in response.Messages)
                {
                    await ProcessMessageAsync(message, stoppingToken);
                }
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error processing SQS messages");
                await Task.Delay(TimeSpan.FromSeconds(5), stoppingToken);
            }
        }

        _logger.LogInformation("SNS Consumer stopping");
    }

    private async Task<string> GetOrCreateQueueUrlAsync(CancellationToken ct)
    {
        const string queueName = "otterworks-audit-events-queue";
        try
        {
            var response = await _sqsClient.GetQueueUrlAsync(queueName, ct);
            return response.QueueUrl;
        }
        catch (QueueDoesNotExistException)
        {
            var createResponse = await _sqsClient.CreateQueueAsync(new CreateQueueRequest
            {
                QueueName = queueName,
            }, ct);
            return createResponse.QueueUrl;
        }
    }

    private async Task ProcessMessageAsync(Message message, CancellationToken ct)
    {
        try
        {
            var auditEvent = AuditMessageParser.Parse(message.Body, message.MessageId);
            if (auditEvent is null)
            {
                _logger.LogWarning("Failed to deserialize audit event from message {MessageId}", message.MessageId);
                await _sqsClient.DeleteMessageAsync(_queueUrl, message.ReceiptHandle, ct);
                return;
            }

            await _repository.SaveEventAsync(auditEvent);
            _logger.LogDebug("Processed SNS event: {Action} on {ResourceType}/{ResourceId}",
                auditEvent.Action, auditEvent.ResourceType, auditEvent.ResourceId);

            await _sqsClient.DeleteMessageAsync(_queueUrl, message.ReceiptHandle, ct);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to process message {MessageId}", message.MessageId);
        }
    }
}
