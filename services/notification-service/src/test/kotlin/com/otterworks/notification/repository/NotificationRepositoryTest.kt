package com.otterworks.notification.repository

import aws.sdk.kotlin.services.dynamodb.DynamoDbClient
import aws.sdk.kotlin.services.dynamodb.model.AttributeValue
import aws.sdk.kotlin.services.dynamodb.model.DeleteItemRequest
import aws.sdk.kotlin.services.dynamodb.model.DeleteItemResponse
import aws.sdk.kotlin.services.dynamodb.model.GetItemRequest
import aws.sdk.kotlin.services.dynamodb.model.GetItemResponse
import aws.sdk.kotlin.services.dynamodb.model.PutItemRequest
import aws.sdk.kotlin.services.dynamodb.model.PutItemResponse
import aws.sdk.kotlin.services.dynamodb.model.QueryRequest
import aws.sdk.kotlin.services.dynamodb.model.QueryResponse
import aws.sdk.kotlin.services.dynamodb.model.UpdateItemRequest
import aws.sdk.kotlin.services.dynamodb.model.UpdateItemResponse
import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class NotificationRepositoryTest {

    private val dynamo = mockk<DynamoDbClient>()
    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "q",
        snsTopicArn = "t",
        dynamoDbTableNotifications = "notifications-table",
        dynamoDbTablePreferences = "preferences-table",
        sesFromEmail = "e",
        sqsPollIntervalMs = 1000,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 5,
    )
    private val repository = NotificationRepository(dynamo, config)

    private fun item(id: String, read: Boolean = false) = mapOf(
        "id" to AttributeValue.S(id),
        "userId" to AttributeValue.S("user-1"),
        "type" to AttributeValue.S("file_shared"),
        "title" to AttributeValue.S("Title $id"),
        "message" to AttributeValue.S("Message"),
        "resourceId" to AttributeValue.S("file-1"),
        "resourceType" to AttributeValue.S("file"),
        "actorId" to AttributeValue.S("actor-1"),
        "read" to AttributeValue.Bool(read),
        "deliveredVia" to AttributeValue.L(listOf(AttributeValue.S("in_app"), AttributeValue.S("push"))),
        "createdAt" to AttributeValue.S("2024-01-01T00:00:00Z"),
    )

    @Test
    fun `saveNotification writes every field to the notifications table`() = runTest {
        val request = slot<PutItemRequest>()
        coEvery { dynamo.putItem(capture(request)) } returns PutItemResponse {}

        repository.saveNotification(
            Notification(
                id = "n-1",
                userId = "user-1",
                type = "file_shared",
                title = "Title n-1",
                message = "Message",
                resourceId = "file-1",
                resourceType = "file",
                actorId = "actor-1",
                deliveredVia = listOf("in_app", "push"),
                createdAt = "2024-01-01T00:00:00Z",
            ),
        )

        assertEquals("notifications-table", request.captured.tableName)
        assertEquals(item("n-1"), request.captured.item)
    }

    @Test
    fun `getNotificationById maps the stored item`() = runTest {
        val request = slot<GetItemRequest>()
        coEvery { dynamo.getItem(capture(request)) } returns GetItemResponse { item = item("n-1", read = true) }

        val notification = repository.getNotificationById("n-1")!!

        assertEquals(mapOf("id" to AttributeValue.S("n-1")), request.captured.key)
        assertEquals("n-1", notification.id)
        assertTrue(notification.read)
        assertEquals(listOf("in_app", "push"), notification.deliveredVia)
        assertEquals("actor-1", notification.actorId)
    }

    @Test
    fun `getNotificationById returns null when missing or malformed`() = runTest {
        coEvery { dynamo.getItem(any<GetItemRequest>()) } returnsMany listOf(
            GetItemResponse {},
            GetItemResponse { item = mapOf("userId" to AttributeValue.S("user-1")) },
        )

        assertNull(repository.getNotificationById("missing"))
        assertNull(repository.getNotificationById("no-id"))
    }

    @Test
    fun `getNotificationsByUserId follows pagination and pages in memory`() = runTest {
        val requests = mutableListOf<QueryRequest>()
        val cursor = mapOf("id" to AttributeValue.S("n-2"))
        coEvery { dynamo.query(capture(requests)) } returnsMany listOf(
            QueryResponse { items = listOf(item("n-1"), item("n-2")); lastEvaluatedKey = cursor },
            QueryResponse { items = listOf(item("n-3")) },
        )

        val (page, total) = repository.getNotificationsByUserId("user-1", page = 2, pageSize = 2)

        assertEquals(3, total)
        assertEquals(listOf("n-3"), page.map { it.id })
        assertEquals(2, requests.size)
        assertEquals("userId-createdAt-index", requests[0].indexName)
        assertEquals(false, requests[0].scanIndexForward)
        assertNull(requests[0].exclusiveStartKey)
        assertEquals(cursor, requests[1].exclusiveStartKey)
    }

    @Test
    fun `getUnreadCount sums counts across pages`() = runTest {
        val requests = mutableListOf<QueryRequest>()
        coEvery { dynamo.query(capture(requests)) } returnsMany listOf(
            QueryResponse { count = 2; lastEvaluatedKey = mapOf("id" to AttributeValue.S("x")) },
            QueryResponse { count = 3 },
        )

        assertEquals(5, repository.getUnreadCount("user-1"))
        assertEquals("#r = :readVal", requests[0].filterExpression)
        assertEquals(AttributeValue.Bool(false), requests[0].expressionAttributeValues!![":readVal"])
    }

    @Test
    fun `markAsRead is conditional on the item existing`() = runTest {
        val request = slot<UpdateItemRequest>()
        coEvery { dynamo.updateItem(capture(request)) } returns UpdateItemResponse {}

        assertTrue(repository.markAsRead("n-1"))
        assertEquals("attribute_exists(id)", request.captured.conditionExpression)
        assertEquals(AttributeValue.Bool(true), request.captured.expressionAttributeValues!![":readVal"])
    }

    @Test
    fun `markAsRead returns false when the item does not exist`() = runTest {
        coEvery { dynamo.updateItem(any<UpdateItemRequest>()) } throws
            RuntimeException("ConditionalCheckFailedException: The conditional request failed")

        assertFalse(repository.markAsRead("missing"))
    }

    @Test
    fun `markAllAsRead marks only unread notifications`() = runTest {
        coEvery { dynamo.query(any<QueryRequest>()) } returns
            QueryResponse { items = listOf(item("n-1"), item("n-2", read = true), item("n-3")) }
        val updates = mutableListOf<UpdateItemRequest>()
        coEvery { dynamo.updateItem(capture(updates)) } returns UpdateItemResponse {}

        assertEquals(2, repository.markAllAsRead("user-1"))
        assertEquals(
            listOf("n-1", "n-3"),
            updates.map { (it.key!!["id"] as AttributeValue.S).value },
        )
    }

    @Test
    fun `deleteNotification reports success and failure`() = runTest {
        coEvery { dynamo.deleteItem(any<DeleteItemRequest>()) } returns
            DeleteItemResponse {} andThenThrows RuntimeException("boom")

        assertTrue(repository.deleteNotification("n-1"))
        assertFalse(repository.deleteNotification("n-1"))
    }

    @Test
    fun `getPreferences falls back to defaults when none are stored`() = runTest {
        coEvery { dynamo.getItem(any<GetItemRequest>()) } returns GetItemResponse {}

        assertEquals(NotificationPreference(userId = "user-1"), repository.getPreferences("user-1"))
    }

    @Test
    fun `getPreferences drops unknown channel names`() = runTest {
        val request = slot<GetItemRequest>()
        coEvery { dynamo.getItem(capture(request)) } returns GetItemResponse {
            item = mapOf(
                "userId" to AttributeValue.S("user-1"),
                "channels" to AttributeValue.M(
                    mapOf(
                        "file_shared" to AttributeValue.L(listOf(AttributeValue.S("EMAIL"), AttributeValue.S("SMS"))),
                        "comment_added" to AttributeValue.S("not-a-list"),
                    ),
                ),
            )
        }

        val prefs = repository.getPreferences("user-1")

        assertEquals("preferences-table", request.captured.tableName)
        assertEquals(
            mapOf("file_shared" to listOf(DeliveryChannel.EMAIL), "comment_added" to emptyList<DeliveryChannel>()),
            prefs.channels,
        )
    }

    @Test
    fun `savePreferences round-trips through getPreferences`() = runTest {
        val put = slot<PutItemRequest>()
        coEvery { dynamo.putItem(capture(put)) } returns PutItemResponse {}
        val prefs = NotificationPreference(
            userId = "user-1",
            channels = mapOf("file_shared" to listOf(DeliveryChannel.PUSH, DeliveryChannel.IN_APP)),
        )

        repository.savePreferences(prefs)

        assertEquals("preferences-table", put.captured.tableName)
        coEvery { dynamo.getItem(any<GetItemRequest>()) } returns GetItemResponse { item = put.captured.item }
        assertEquals(prefs, repository.getPreferences("user-1"))
        coVerify(exactly = 1) { dynamo.putItem(any<PutItemRequest>()) }
    }
}
