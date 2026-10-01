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

    private val dynamoDbClient = mockk<DynamoDbClient>()
    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "http://localhost:4566/000000000000/test-queue",
        snsTopicArn = "arn:aws:sns:us-east-1:000000000000:test-topic",
        dynamoDbTableNotifications = "test-notifications",
        dynamoDbTablePreferences = "test-preferences",
        sesFromEmail = "test@otterworks.io",
        sqsPollIntervalMs = 1000,
        sqsMaxMessages = 10,
        sqsWaitTimeSeconds = 5,
    )

    private val repository = NotificationRepository(dynamoDbClient, config)

    private fun notification(
        id: String = "n-1",
        userId: String = "user-1",
        read: Boolean = false,
    ) = Notification(
        id = id,
        userId = userId,
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

    private fun item(
        id: String = "n-1",
        userId: String = "user-1",
        read: Boolean = false,
    ): Map<String, AttributeValue> = mapOf(
        "id" to AttributeValue.S(id),
        "userId" to AttributeValue.S(userId),
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
    fun `saveNotification writes every field to the notifications table`() = runTest {
        val request = slot<PutItemRequest>()
        coEvery { dynamoDbClient.putItem(capture(request)) } returns PutItemResponse {}

        repository.saveNotification(notification())

        assertEquals("test-notifications", request.captured.tableName)
        val written = request.captured.item!!
        assertEquals(AttributeValue.S("n-1"), written["id"])
        assertEquals(AttributeValue.S("user-1"), written["userId"])
        assertEquals(AttributeValue.S("file_shared"), written["type"])
        assertEquals(AttributeValue.Bool(false), written["read"])
        assertEquals(
            listOf(AttributeValue.S("in_app"), AttributeValue.S("email")),
            (written["deliveredVia"] as AttributeValue.L).value,
        )
    }

    @Test
    fun `getNotificationById maps a stored item back into a Notification`() = runTest {
        val request = slot<GetItemRequest>()
        coEvery { dynamoDbClient.getItem(capture(request)) } returns GetItemResponse { item = item(read = true) }

        val found = repository.getNotificationById("n-1")

        assertEquals("test-notifications", request.captured.tableName)
        assertEquals(mapOf("id" to AttributeValue.S("n-1")), request.captured.key)
        assertEquals("n-1", found?.id)
        assertEquals("user-1", found?.userId)
        assertEquals("File Shared With You", found?.title)
        assertEquals(listOf("in_app"), found?.deliveredVia)
        assertTrue(found!!.read)
    }

    @Test
    fun `getNotificationById returns null when the item does not exist`() = runTest {
        coEvery { dynamoDbClient.getItem(any<GetItemRequest>()) } returns GetItemResponse {}

        assertNull(repository.getNotificationById("missing"))
    }

    @Test
    fun `getNotificationById skips items that are missing the key attributes`() = runTest {
        coEvery { dynamoDbClient.getItem(any<GetItemRequest>()) } returns GetItemResponse {
            item = mapOf("title" to AttributeValue.S("orphan"))
        }

        assertNull(repository.getNotificationById("n-1"))
    }

    @Test
    fun `getNotificationsByUserId follows pagination tokens and returns the requested page`() = runTest {
        val requests = mutableListOf<QueryRequest>()
        coEvery { dynamoDbClient.query(capture(requests)) } returnsMany listOf(
            QueryResponse {
                items = listOf(item(id = "n-1"), item(id = "n-2"))
                lastEvaluatedKey = mapOf("id" to AttributeValue.S("n-2"))
            },
            QueryResponse { items = listOf(item(id = "n-3")) },
        )

        val (page, total) = repository.getNotificationsByUserId("user-1", page = 2, pageSize = 2)

        assertEquals(3, total)
        assertEquals(listOf("n-3"), page.map { it.id })
        assertEquals(2, requests.size)
        assertEquals("userId-createdAt-index", requests[0].indexName)
        assertEquals(false, requests[0].scanIndexForward)
        assertNull(requests[0].exclusiveStartKey)
        assertEquals(mapOf("id" to AttributeValue.S("n-2")), requests[1].exclusiveStartKey)
    }

    @Test
    fun `getNotificationsByUserId returns an empty page past the end of the results`() = runTest {
        coEvery { dynamoDbClient.query(any<QueryRequest>()) } returns QueryResponse { items = listOf(item()) }

        val (page, total) = repository.getNotificationsByUserId("user-1", page = 5, pageSize = 20)

        assertEquals(1, total)
        assertTrue(page.isEmpty())
    }

    @Test
    fun `getUnreadCount sums the counts of every page`() = runTest {
        val requests = mutableListOf<QueryRequest>()
        coEvery { dynamoDbClient.query(capture(requests)) } returnsMany listOf(
            QueryResponse {
                count = 2
                lastEvaluatedKey = mapOf("id" to AttributeValue.S("n-2"))
            },
            QueryResponse { count = 3 },
        )

        assertEquals(5, repository.getUnreadCount("user-1"))
        assertEquals("#r = :readVal", requests[0].filterExpression)
        assertEquals(mapOf("#r" to "read"), requests[0].expressionAttributeNames)
        assertEquals(AttributeValue.Bool(false), requests[0].expressionAttributeValues?.get(":readVal"))
    }

    @Test
    fun `markAsRead issues a conditional update and reports success`() = runTest {
        val request = slot<UpdateItemRequest>()
        coEvery { dynamoDbClient.updateItem(capture(request)) } returns UpdateItemResponse {}

        assertTrue(repository.markAsRead("n-1"))
        assertEquals("SET #r = :readVal", request.captured.updateExpression)
        assertEquals("attribute_exists(id)", request.captured.conditionExpression)
        assertEquals(AttributeValue.Bool(true), request.captured.expressionAttributeValues?.get(":readVal"))
    }

    @Test
    fun `markAsRead reports failure when the conditional update is rejected`() = runTest {
        coEvery { dynamoDbClient.updateItem(any<UpdateItemRequest>()) } throws RuntimeException("condition failed")

        assertFalse(repository.markAsRead("missing"))
    }

    @Test
    fun `markAllAsRead only updates the unread notifications of the user`() = runTest {
        coEvery { dynamoDbClient.query(any<QueryRequest>()) } returns QueryResponse {
            items = listOf(item(id = "n-1", read = false), item(id = "n-2", read = true), item(id = "n-3", read = false))
        }
        val updates = mutableListOf<UpdateItemRequest>()
        coEvery { dynamoDbClient.updateItem(capture(updates)) } returns UpdateItemResponse {}

        assertEquals(2, repository.markAllAsRead("user-1"))
        assertEquals(
            listOf(AttributeValue.S("n-1"), AttributeValue.S("n-3")),
            updates.map { it.key!!.getValue("id") },
        )
    }

    @Test
    fun `deleteNotification returns true on success and false when DynamoDB fails`() = runTest {
        val request = slot<DeleteItemRequest>()
        coEvery { dynamoDbClient.deleteItem(capture(request)) } returns DeleteItemResponse {}
        assertTrue(repository.deleteNotification("n-1"))
        assertEquals(mapOf("id" to AttributeValue.S("n-1")), request.captured.key)

        coEvery { dynamoDbClient.deleteItem(any<DeleteItemRequest>()) } throws RuntimeException("boom")
        assertFalse(repository.deleteNotification("n-1"))
    }

    @Test
    fun `getPreferences maps stored channels and drops unknown channel names`() = runTest {
        coEvery { dynamoDbClient.getItem(any<GetItemRequest>()) } returns GetItemResponse {
            item = mapOf(
                "userId" to AttributeValue.S("user-1"),
                "channels" to AttributeValue.M(
                    mapOf(
                        "file_shared" to AttributeValue.L(
                            listOf(AttributeValue.S("EMAIL"), AttributeValue.S("SMS_PIGEON")),
                        ),
                        "comment_added" to AttributeValue.L(listOf(AttributeValue.S("IN_APP"))),
                    ),
                ),
            )
        }

        val preferences = repository.getPreferences("user-1")

        assertEquals("user-1", preferences.userId)
        assertEquals(listOf(DeliveryChannel.EMAIL), preferences.channels["file_shared"])
        assertEquals(listOf(DeliveryChannel.IN_APP), preferences.channels["comment_added"])
    }

    @Test
    fun `getPreferences falls back to the default preference set for unknown users`() = runTest {
        coEvery { dynamoDbClient.getItem(any<GetItemRequest>()) } returns GetItemResponse {}

        val preferences = repository.getPreferences("new-user")

        assertEquals(NotificationPreference(userId = "new-user"), preferences)
        assertEquals(
            listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP, DeliveryChannel.PUSH),
            preferences.channels["file_shared"],
        )
    }

    @Test
    fun `savePreferences flattens channels into a DynamoDB map on the preferences table`() = runTest {
        val request = slot<PutItemRequest>()
        coEvery { dynamoDbClient.putItem(capture(request)) } returns PutItemResponse {}

        repository.savePreferences(
            NotificationPreference(
                userId = "user-1",
                channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH)),
            ),
        )

        assertEquals("test-preferences", request.captured.tableName)
        val channels = (request.captured.item!!.getValue("channels") as AttributeValue.M).value
        assertEquals(
            listOf(AttributeValue.S("EMAIL"), AttributeValue.S("PUSH")),
            (channels.getValue("file_shared") as AttributeValue.L).value,
        )
        coVerify(exactly = 1) { dynamoDbClient.putItem(any<PutItemRequest>()) }
    }
}
