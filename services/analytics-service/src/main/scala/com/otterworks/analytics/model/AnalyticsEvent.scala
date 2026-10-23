package com.otterworks.analytics.model

import spray.json.*
import java.time.Instant
import java.util.UUID

/** Raw analytics event ingested from SQS or the REST API. */
final case class AnalyticsEvent(
    eventId: String,
    eventType: String,
    userId: String,
    resourceId: String,
    resourceType: String,
    metadata: Map[String, String],
    timestamp: Instant
)

object AnalyticsEvent:
  def create(
      eventType: String,
      userId: String,
      resourceId: String,
      resourceType: String,
      metadata: Map[String, String] = Map.empty
  ): AnalyticsEvent =
    AnalyticsEvent(
      eventId = UUID.randomUUID().toString,
      eventType = eventType,
      userId = userId,
      resourceId = resourceId,
      resourceType = resourceType,
      metadata = metadata,
      timestamp = Instant.now()
    )

/** Supported event types across the OtterWorks platform. */
object EventType:
  val DocumentCreated = "document.created"
  val DocumentViewed = "document.viewed"
  val DocumentEdited = "document.edited"
  val DocumentShared = "document.shared"
  val DocumentDeleted = "document.deleted"
  val FileUploaded = "file.uploaded"
  val FileDownloaded = "file.downloaded"
  val FileDeleted = "file.deleted"
  val FileShared = "file.shared"
  val UserLoggedIn = "user.logged_in"
  val UserLoggedOut = "user.logged_out"
  val CollabSessionStarted = "collab.session_started"
  val CollabSessionEnded = "collab.session_ended"
  val StorageAllocated = "storage.allocated"
  val StorageReleased = "storage.released"

  val All: Set[String] = Set(
    DocumentCreated, DocumentViewed, DocumentEdited, DocumentShared, DocumentDeleted,
    FileUploaded, FileDownloaded, FileDeleted, FileShared,
    UserLoggedIn, UserLoggedOut,
    CollabSessionStarted, CollabSessionEnded,
    StorageAllocated, StorageReleased
  )

/**
 * Validation for events submitted over the REST ingest. Storage accounting
 * events are excluded: they are produced by internal services on the SQS queue,
 * and accepting them from callers would let anyone rewrite storage totals.
 * Identifiers are restricted to a plain charset so exported CSV cells can never
 * start with a spreadsheet formula character.
 */
object TrackEventPolicy:
  val MaxBodyBytes: Long = 16 * 1024
  val MaxMetadataEntries = 16
  val MaxMetadataKeyLength = 64
  val MaxMetadataValueLength = 512

  val RestIngestibleEventTypes: Set[String] =
    EventType.All -- Set(EventType.StorageAllocated, EventType.StorageReleased)

  private val ResourceIdPattern = "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$".r
  private val ResourceTypePattern = "^[a-z][a-z0-9_.-]{0,31}$".r
  private val MetadataKeyPattern = s"^[A-Za-z0-9_.-]{1,$MaxMetadataKeyLength}$$".r

  def validate(request: AnalyticsEventJsonProtocol.TrackEventRequest): Either[String, Unit] =
    val metadata = request.metadata.getOrElse(Map.empty)
    if !RestIngestibleEventTypes.contains(request.eventType) then
      Left("eventType must be one of: " + RestIngestibleEventTypes.toList.sorted.mkString(", "))
    else if ResourceIdPattern.findFirstIn(request.resourceId).isEmpty then
      Left("resourceId must be 1-128 characters of [A-Za-z0-9_.:-] starting with a letter or digit")
    else if ResourceTypePattern.findFirstIn(request.resourceType).isEmpty then
      Left("resourceType must be 1-32 characters of [a-z0-9_.-] starting with a letter")
    else if metadata.size > MaxMetadataEntries then
      Left(s"metadata may contain at most $MaxMetadataEntries entries")
    else if metadata.keys.exists(k => MetadataKeyPattern.findFirstIn(k).isEmpty) then
      Left(s"metadata keys must be 1-$MaxMetadataKeyLength characters of [A-Za-z0-9_.-]")
    else if metadata.values.exists(v => v.length > MaxMetadataValueLength || v.exists(_.isControl)) then
      Left(s"metadata values must be at most $MaxMetadataValueLength characters with no control characters")
    else Right(())

/** Spray JSON formats for AnalyticsEvent serialization. */
object AnalyticsEventJsonProtocol extends DefaultJsonProtocol:

  given instantFormat: JsonFormat[Instant] = new JsonFormat[Instant]:
    def write(instant: Instant): JsValue = JsString(instant.toString)
    def read(json: JsValue): Instant = json match
      case JsString(s) => Instant.parse(s)
      case JsNumber(n) => Instant.ofEpochMilli(n.toLong)
      case other        => deserializationError(s"Expected ISO-8601 string or epoch millis, got $other")

  given analyticsEventFormat: RootJsonFormat[AnalyticsEvent] =
    jsonFormat7(AnalyticsEvent.apply)

  /**
   * Request payload for POST /api/v1/analytics/events. `userId` is optional and,
   * when present, must equal the authenticated caller.
   */
  final case class TrackEventRequest(
      eventType: String,
      userId: Option[String],
      resourceId: String,
      resourceType: String,
      metadata: Option[Map[String, String]]
  )

  given trackEventRequestFormat: RootJsonFormat[TrackEventRequest] =
    jsonFormat5(TrackEventRequest.apply)

  /** Standard accepted response. */
  final case class AcceptedResponse(status: String, eventId: String)
  given acceptedResponseFormat: RootJsonFormat[AcceptedResponse] =
    jsonFormat2(AcceptedResponse.apply)

  final case class ErrorResponse(error: String)
  given errorResponseFormat: RootJsonFormat[ErrorResponse] =
    jsonFormat1(ErrorResponse.apply)
