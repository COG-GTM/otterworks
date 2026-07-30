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

    private val dynamoDbClient = mockk<DynamoDbClient>(relaxed = true)
    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "http://localhost:4566/000000000000/test-queue",
        snsTopicArn = "arn:aws:sns:us-east-1:000000000000:test-topic",
        dynamoDbTableNotifications = "test-notifications",
        dynamoDbTablePreferences = "test-preferences",
        sesFromEmail = "notifications@otterworks.io",
        sqsPollIntervalMs = 1000,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 5,
    )
    private val repository = NotificationRepository(dynamoDbClient, config)

    private fun notification(id: String, read: Boolean = false) = Notification(
        id = id,
        userId = "user-1",
        type = "file_shared",
        title = "File Shared With You",
        message = "A file has been shared with you.",
        resourceId = "file-1",
        resourceType = "file",
        actorId = "actor-1",
        read = read,
        deliveredVia = listOf("in_app", "email"),
        createdAt = "2024-01-01T00:00:00Z",
    )

    private fun item(id: String, read: Boolean = false): Map<String, AttributeValue> = mapOf(
        "id" to AttributeValue.S(id),
        "userId" to AttributeValue.S("user-1"),
        "type" to AttributeValue.S("file_shared"),
        "title" to AttributeValue.S("File Shared With You"),
        "message" to AttributeValue.S("A file has been shared with you."),
        "resourceId" to AttributeValue.S("file-1"),
        "resourceType" to AttributeValue.S("file"),
        "actorId" to AttributeValue.S("actor-1"),
        "read" to AttributeValue.Bool(read),
        "deliveredVia" to AttributeValue.L(listOf(AttributeValue.S("in_app"))),
        "createdAt" to AttributeValue.S("2024-01-01T00:00:00Z"),
    )

    @Test
    fun `saveNotification writes every attribute to the notifications table`() = runTest {
        val request = slot<PutItemRequest>()
        coEvery { dynamoDbClient.putItem(capture(request)) } returns PutItemResponse {}

        repository.saveNotification(notification("notif-1"))

        val captured = request.captured
        assertEquals("test-notifications", captured.tableName)
        val written = captured.item!!
        assertEquals(AttributeValue.S("notif-1"), written["id"])
        assertEquals(AttributeValue.S("user-1"), written["userId"])
        assertEquals(AttributeValue.S("file_shared"), written["type"])
        assertEquals(AttributeValue.S("file-1"), written["resourceId"])
        assertEquals(AttributeValue.S("actor-1"), written["actorId"])
        assertEquals(AttributeValue.Bool(false), written["read"])
        assertEquals(
            AttributeValue.L(listOf(AttributeValue.S("in_app"), AttributeValue.S("email"))),
            written["deliveredVia"],
        )
    }

    @Test
    fun `getNotificationById maps a stored item`() = runTest {
        coEvery { dynamoDbClient.getItem(any<GetItemRequest>()) } returns
            GetItemResponse { item = item("notif-1", read = true) }

        val found = repository.getNotificationById("notif-1")

        assertEquals("notif-1", found?.id)
        assertEquals("user-1", found?.userId)
        assertEquals("file_shared", found?.type)
        assertEquals(listOf("in_app"), found?.deliveredVia)
        assertTrue(found!!.read)
    }

    @Test
    fun `getNotificationById returns null when the item is missing`() = runTest {
        coEvery { dynamoDbClient.getItem(any<GetItemRequest>()) } returns GetItemResponse {}

        assertNull(repository.getNotificationById("missing"))
    }

    @Test
    fun `getNotificationById returns null when the item has no id or userId`() = runTest {
        coEvery { dynamoDbClient.getItem(any<GetItemRequest>()) } returns
            GetItemResponse { item = mapOf("title" to AttributeValue.S("orphan")) }

        assertNull(repository.getNotificationById("notif-1"))
    }

    @Test
    fun `getNotificationById defaults optional attributes that are absent`() = runTest {
        coEvery { dynamoDbClient.getItem(any<GetItemRequest>()) } returns GetItemResponse {
            item = mapOf(
                "id" to AttributeValue.S("notif-1"),
                "userId" to AttributeValue.S("user-1"),
            )
        }

        val found = repository.getNotificationById("notif-1")!!

        assertEquals("", found.type)
        assertEquals("", found.title)
        assertEquals("", found.message)
        assertEquals("", found.resourceId)
        assertEquals("", found.resourceType)
        assertEquals("", found.actorId)
        assertEquals("", found.createdAt)
        assertFalse(found.read)
        assertEquals(emptyList(), found.deliveredVia)
    }

    @Test
    fun `getNotificationsByUserId follows pagination and slices the requested page`() = runTest {
        val requests = mutableListOf<QueryRequest>()
        coEvery { dynamoDbClient.query(capture(requests)) } returnsMany listOf(
            QueryResponse {
                items = listOf(item("notif-1"), item("notif-2"))
                count = 2
                lastEvaluatedKey = mapOf("id" to AttributeValue.S("notif-2"))
            },
            QueryResponse {
                items = listOf(item("notif-3"))
                count = 1
            },
        )

        val (page, total) = repository.getNotificationsByUserId("user-1", page = 2, pageSize = 2)

        assertEquals(3, total)
        assertEquals(listOf("notif-3"), page.map { it.id })
        assertEquals(2, requests.size)
        assertEquals("userId-createdAt-index", requests[0].indexName)
        assertEquals("userId = :uid", requests[0].keyConditionExpression)
        assertNull(requests[0].exclusiveStartKey)
        assertEquals(mapOf("id" to AttributeValue.S("notif-2")), requests[1].exclusiveStartKey)
    }

    @Test
    fun `getNotificationsByUserId drops items that cannot be mapped`() = runTest {
        coEvery { dynamoDbClient.query(any<QueryRequest>()) } returns QueryResponse {
            items = listOf(item("notif-1"), mapOf("title" to AttributeValue.S("orphan")))
            count = 2
        }

        val (page, total) = repository.getNotificationsByUserId("user-1")

        assertEquals(1, total)
        assertEquals(listOf("notif-1"), page.map { it.id })
    }

    @Test
    fun `getUnreadCount sums the count across pages`() = runTest {
        val request = slot<QueryRequest>()
        coEvery { dynamoDbClient.query(capture(request)) } returnsMany listOf(
            QueryResponse {
                count = 4
                lastEvaluatedKey = mapOf("id" to AttributeValue.S("notif-4"))
            },
            QueryResponse { count = 3 },
        )

        assertEquals(7, repository.getUnreadCount("user-1"))
        assertEquals("#r = :readVal", request.captured.filterExpression)
        assertEquals(mapOf("#r" to "read"), request.captured.expressionAttributeNames)
    }

    @Test
    fun `markAsRead updates the record and reports success`() = runTest {
        val request = slot<UpdateItemRequest>()
        coEvery { dynamoDbClient.updateItem(capture(request)) } returns UpdateItemResponse {}

        assertTrue(repository.markAsRead("notif-1"))
        assertEquals("SET #r = :readVal", request.captured.updateExpression)
        assertEquals("attribute_exists(id)", request.captured.conditionExpression)
        assertEquals(mapOf("id" to AttributeValue.S("notif-1")), request.captured.key)
    }

    @Test
    fun `markAsRead reports failure when the conditional update is rejected`() = runTest {
        coEvery { dynamoDbClient.updateItem(any<UpdateItemRequest>()) } throws
            IllegalStateException("conditional check failed")

        assertFalse(repository.markAsRead("missing"))
    }

    @Test
    fun `markAllAsRead only updates the unread notifications`() = runTest {
        coEvery { dynamoDbClient.query(any<QueryRequest>()) } returns QueryResponse {
            items = listOf(item("notif-1"), item("notif-2", read = true), item("notif-3"))
            count = 3
        }
        coEvery { dynamoDbClient.updateItem(any<UpdateItemRequest>()) } returns UpdateItemResponse {}

        assertEquals(2, repository.markAllAsRead("user-1"))
        coVerify(exactly = 2) { dynamoDbClient.updateItem(any<UpdateItemRequest>()) }
    }

    @Test
    fun `deleteNotification reports success and failure`() = runTest {
        val request = slot<DeleteItemRequest>()
        coEvery { dynamoDbClient.deleteItem(capture(request)) } returns DeleteItemResponse {}
        assertTrue(repository.deleteNotification("notif-1"))
        assertEquals("test-notifications", request.captured.tableName)

        coEvery { dynamoDbClient.deleteItem(any<DeleteItemRequest>()) } throws
            IllegalStateException("dynamo unavailable")
        assertFalse(repository.deleteNotification("notif-1"))
    }

    @Test
    fun `getPreferences maps stored channels and skips unknown ones`() = runTest {
        val request = slot<GetItemRequest>()
        coEvery { dynamoDbClient.getItem(capture(request)) } returns GetItemResponse {
            item = mapOf(
                "userId" to AttributeValue.S("user-1"),
                "channels" to AttributeValue.M(
                    mapOf(
                        "file_shared" to AttributeValue.L(
                            listOf(
                                AttributeValue.S("EMAIL"),
                                AttributeValue.S("SMOKE_SIGNAL"),
                                AttributeValue.Bool(true),
                            )
                        ),
                        "comment_added" to AttributeValue.S("not-a-list"),
                    )
                ),
            )
        }

        val preferences = repository.getPreferences("user-1")

        assertEquals("test-preferences", request.captured.tableName)
        assertEquals("user-1", preferences.userId)
        assertEquals(listOf(DeliveryChannel.EMAIL), preferences.channels["file_shared"])
        assertEquals(emptyList(), preferences.channels["comment_added"])
    }

    @Test
    fun `getPreferences falls back to defaults when nothing is stored`() = runTest {
        coEvery { dynamoDbClient.getItem(any<GetItemRequest>()) } returns GetItemResponse {}

        val preferences = repository.getPreferences("user-1")

        assertEquals(NotificationPreference(userId = "user-1"), preferences)
    }

    @Test
    fun `getPreferences falls back to defaults when the stored item has no userId`() = runTest {
        coEvery { dynamoDbClient.getItem(any<GetItemRequest>()) } returns
            GetItemResponse { item = mapOf("channels" to AttributeValue.M(emptyMap())) }

        assertEquals(NotificationPreference(userId = "user-1"), repository.getPreferences("user-1"))
    }

    @Test
    fun `getPreferences yields no channels when the channels attribute is not a map`() = runTest {
        coEvery { dynamoDbClient.getItem(any<GetItemRequest>()) } returns GetItemResponse {
            item = mapOf(
                "userId" to AttributeValue.S("user-1"),
                "channels" to AttributeValue.S("corrupt"),
            )
        }

        assertEquals(emptyMap(), repository.getPreferences("user-1").channels)
    }

    @Test
    fun `savePreferences flattens channels into a DynamoDB map`() = runTest {
        val request = slot<PutItemRequest>()
        coEvery { dynamoDbClient.putItem(capture(request)) } returns PutItemResponse {}

        repository.savePreferences(
            NotificationPreference(
                userId = "user-1",
                channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH)),
            )
        )

        assertEquals("test-preferences", request.captured.tableName)
        assertEquals(
            AttributeValue.M(
                mapOf(
                    "file_shared" to AttributeValue.L(
                        listOf(AttributeValue.S("EMAIL"), AttributeValue.S("PUSH"))
                    )
                )
            ),
            request.captured.item!!["channels"],
        )
    }
}
