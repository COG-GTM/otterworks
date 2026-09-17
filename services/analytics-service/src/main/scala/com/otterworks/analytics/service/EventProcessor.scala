package com.otterworks.analytics.service

import akka.actor.typed.ActorSystem
import akka.stream.scaladsl.{Sink, Source}
import com.otterworks.analytics.config.{AppConfig, SqsConfig}
import org.slf4j.LoggerFactory
import io.circe.parser.decode
import io.circe.generic.auto.*
import software.amazon.awssdk.auth.credentials.DefaultCredentialsProvider
import software.amazon.awssdk.regions.Region
import software.amazon.awssdk.services.sqs.SqsClient
import software.amazon.awssdk.services.sqs.model.{DeleteMessageRequest, ReceiveMessageRequest}

import java.net.URI
import scala.concurrent.{ExecutionContext, Future}
import scala.concurrent.duration.*
import scala.jdk.CollectionConverters.*
import scala.util.{Failure, Success, Try}

/**
 * SQS-based event processor that consumes analytics events from a queue
 * and feeds them into the AnalyticsService for processing and storage.
 *
 * Uses Akka Streams for backpressure-aware processing of incoming events.
 */
class EventProcessor(
    config: AppConfig,
    analyticsService: AnalyticsService
)(using system: ActorSystem[?], ec: ExecutionContext):

  private val logger = LoggerFactory.getLogger(getClass)

  protected lazy val sqsClient: SqsClient =
    val builder = SqsClient.builder()
      .region(Region.of(config.aws.region))
      .credentialsProvider(DefaultCredentialsProvider.create())
    config.aws.endpointUrl.foreach(url => builder.endpointOverride(URI.create(url)))
    builder.build()

  /** Raw SQS message payload for circe decoding. */
  private case class SqsEventPayload(
      eventType: String,
      userId: String,
      resourceId: String,
      resourceType: String,
      metadata: Option[Map[String, String]]
  )

  /**
   * Start polling SQS for events. This runs as an Akka Stream that
   * periodically receives messages, processes them, and deletes them
   * from the queue.
   */
  def start(): Unit =
    logger.info("Starting SQS event processor, queue={}", config.sqs.eventsQueueUrl)

    Source
      .tick(1.second, 5.seconds, ())
      .mapAsync(1) { _ =>
        Future {
          Try {
            val request = ReceiveMessageRequest.builder()
              .queueUrl(config.sqs.eventsQueueUrl)
              .maxNumberOfMessages(10)
              .waitTimeSeconds(2)
              .build()
            sqsClient.receiveMessage(request).messages().asScala.toList
          } match
            case Success(msgs) => msgs
            case Failure(ex) =>
              logger.warn("Failed to receive messages from SQS, will retry", ex)
              List.empty
        }
      }
      .mapConcat(identity)
      .mapAsync(4) { message =>
        decode[SqsEventPayload](message.body()) match
          case Right(payload) =>
            analyticsService
              .trackEvent(
                payload.eventType,
                payload.userId,
                payload.resourceId,
                payload.resourceType,
                payload.metadata.getOrElse(Map.empty)
              )
              .map { event =>
                Try {
                  val deleteReq = DeleteMessageRequest.builder()
                    .queueUrl(config.sqs.eventsQueueUrl)
                    .receiptHandle(message.receiptHandle())
                    .build()
                  sqsClient.deleteMessage(deleteReq)
                } match
                  case Success(_) => logger.debug("Processed SQS event: {}", event.eventId)
                  case Failure(ex) => logger.error("Failed to delete SQS message for event {}: {}", event.eventId, ex.getMessage)
              }
              .recover { case ex =>
                logger.error("Failed to process event from SQS: {}", ex.getMessage)
              }
          case Left(err) =>
            logger.error("Failed to decode SQS message: {}", err.getMessage)
            Try {
              val deleteReq = DeleteMessageRequest.builder()
                .queueUrl(config.sqs.eventsQueueUrl)
                .receiptHandle(message.receiptHandle())
                .build()
              sqsClient.deleteMessage(deleteReq)
            } match
              case Success(_) => logger.warn("Deleted undecodable SQS message")
              case Failure(ex) => logger.error("Failed to delete undecodable SQS message: {}", ex.getMessage)
            Future.successful(())
      }
      .runWith(Sink.ignore)

    logger.info("SQS event processor stream started"): Unit
