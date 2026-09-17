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
import kotlin.test.assertNotNull
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

    private fun notificationItem(
        id: String,
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
        coEvery { dynamoDbClient.putItem(capture(request)) } returns PutItemResponse { }

        repository.saveNotification(
            Notification(
                id = "n-1",
                userId = "user-1",
                type = "file_shared",
                title = "File Shared With You",
                message = "A file has been shared with you.",
                resourceId = "file-1",
                resourceType = "file",
                actorId = "actor-1",
                read = true,
                deliveredVia = listOf("in_app", "email"),
                createdAt = "2024-01-01T00:00:00Z",
            )
        )

        val item = request.captured.item!!
        assertEquals("test-notifications", request.captured.tableName)
        assertEquals(AttributeValue.S("n-1"), item["id"])
        assertEquals(AttributeValue.S("user-1"), item["userId"])
        assertEquals(AttributeValue.S("file_shared"), item["type"])
        assertEquals(AttributeValue.S("actor-1"), item["actorId"])
        assertEquals(AttributeValue.Bool(true), item["read"])
        assertEquals(
            AttributeValue.L(listOf(AttributeValue.S("in_app"), AttributeValue.S("email"))),
            item["deliveredVia"],
        )
        assertEquals(AttributeValue.S("2024-01-01T00:00:00Z"), item["createdAt"])
    }

    @Test
    fun `getNotificationById maps a stored item back to a Notification`() = runTest {
        val request = slot<GetItemRequest>()
        coEvery { dynamoDbClient.getItem(capture(request)) } returns
            GetItemResponse { item = notificationItem("n-1", read = true) }

        val notification = repository.getNotificationById("n-1")

        assertNotNull(notification)
        assertEquals("n-1", notification.id)
        assertEquals("user-1", notification.userId)
        assertEquals("file_shared", notification.type)
        assertEquals("File Shared With You", notification.title)
        assertEquals("file-1", notification.resourceId)
        assertEquals("file", notification.resourceType)
        assertEquals("actor-1", notification.actorId)
        assertTrue(notification.read)
        assertEquals(listOf("in_app"), notification.deliveredVia)
        assertEquals("2024-01-01T00:00:00Z", notification.createdAt)
        assertEquals(mapOf("id" to AttributeValue.S("n-1")), request.captured.key)
    }

    @Test
    fun `getNotificationById returns null when the item does not exist`() = runTest {
        coEvery { dynamoDbClient.getItem(any()) } returns GetItemResponse { item = null }

        assertNull(repository.getNotificationById("missing"))
    }

    @Test
    fun `getNotificationById returns null when the item has no id or userId`() = runTest {
        coEvery { dynamoDbClient.getItem(any()) } returns GetItemResponse {
            item = mapOf("userId" to AttributeValue.S("user-1"))
        }
        assertNull(repository.getNotificationById("n-1"))

        coEvery { dynamoDbClient.getItem(any()) } returns GetItemResponse {
            item = mapOf("id" to AttributeValue.S("n-1"))
        }
        assertNull(repository.getNotificationById("n-1"))
    }

    @Test
    fun `getNotificationById defaults absent optional attributes`() = runTest {
        coEvery { dynamoDbClient.getItem(any()) } returns GetItemResponse {
            item = mapOf(
                "id" to AttributeValue.S("n-1"),
                "userId" to AttributeValue.S("user-1"),
            )
        }

        val notification = repository.getNotificationById("n-1")

        assertNotNull(notification)
        assertEquals("", notification.type)
        assertEquals("", notification.title)
        assertEquals("", notification.message)
        assertEquals("", notification.resourceId)
        assertEquals("", notification.resourceType)
        assertEquals("", notification.actorId)
        assertFalse(notification.read)
        assertEquals(emptyList(), notification.deliveredVia)
        assertEquals("", notification.createdAt)
    }

    @Test
    fun `getNotificationById ignores attributes stored with the wrong type`() = runTest {
        coEvery { dynamoDbClient.getItem(any()) } returns GetItemResponse {
            item = mapOf(
                "id" to AttributeValue.S("n-1"),
                "userId" to AttributeValue.S("user-1"),
                "type" to AttributeValue.N("1"),
                "title" to AttributeValue.N("2"),
                "message" to AttributeValue.N("3"),
                "resourceId" to AttributeValue.N("4"),
                "resourceType" to AttributeValue.N("5"),
                "actorId" to AttributeValue.N("6"),
                "read" to AttributeValue.S("true"),
                "deliveredVia" to AttributeValue.L(
                    listOf(AttributeValue.S("in_app"), AttributeValue.N("7")),
                ),
                "createdAt" to AttributeValue.N("8"),
            )
        }

        val notification = repository.getNotificationById("n-1")

        assertNotNull(notification)
        assertEquals("", notification.type)
        assertEquals("", notification.title)
        assertEquals("", notification.message)
        assertEquals("", notification.resourceId)
        assertEquals("", notification.resourceType)
        assertEquals("", notification.actorId)
        assertFalse(notification.read)
        assertEquals(listOf("in_app"), notification.deliveredVia)
        assertEquals("", notification.createdAt)
    }

    @Test
    fun `getNotificationsByUserId follows pagination tokens and queries newest first`() = runTest {
        val requests = mutableListOf<QueryRequest>()
        coEvery { dynamoDbClient.query(capture(requests)) } returnsMany listOf(
            QueryResponse {
                items = listOf(notificationItem("n-1"), notificationItem("n-2"))
                count = 2
                lastEvaluatedKey = mapOf("id" to AttributeValue.S("n-2"))
            },
            QueryResponse {
                items = listOf(notificationItem("n-3"))
                count = 1
                lastEvaluatedKey = null
            },
        )

        val (page, total) = repository.getNotificationsByUserId("user-1", page = 1, pageSize = 20)

        assertEquals(3, total)
        assertEquals(listOf("n-1", "n-2", "n-3"), page.map { it.id })
        assertEquals(2, requests.size)
        assertEquals("userId-createdAt-index", requests[0].indexName)
        assertEquals(false, requests[0].scanIndexForward)
        assertNull(requests[0].exclusiveStartKey)
        assertEquals(mapOf("id" to AttributeValue.S("n-2")), requests[1].exclusiveStartKey)
    }

    @Test
    fun `getNotificationsByUserId returns only the requested page`() = runTest {
        coEvery { dynamoDbClient.query(any()) } returns QueryResponse {
            items = (1..5).map { notificationItem("n-$it") }
            count = 5
            lastEvaluatedKey = null
        }

        val (page, total) = repository.getNotificationsByUserId("user-1", page = 2, pageSize = 2)

        assertEquals(5, total)
        assertEquals(listOf("n-3", "n-4"), page.map { it.id })
    }

    @Test
    fun `getNotificationsByUserId skips items that cannot be mapped`() = runTest {
        coEvery { dynamoDbClient.query(any()) } returns QueryResponse {
            items = listOf(notificationItem("n-1"), mapOf("userId" to AttributeValue.S("user-1")))
            count = 2
            lastEvaluatedKey = null
        }

        val (page, total) = repository.getNotificationsByUserId("user-1")

        assertEquals(1, total)
        assertEquals(listOf("n-1"), page.map { it.id })
    }

    @Test
    fun `getNotificationsByUserId tolerates a query response without items`() = runTest {
        coEvery { dynamoDbClient.query(any()) } returns QueryResponse {
            items = null
            count = 0
            lastEvaluatedKey = null
        }

        val (page, total) = repository.getNotificationsByUserId("user-1")

        assertEquals(0, total)
        assertTrue(page.isEmpty())
    }

    @Test
    fun `getUnreadCount sums the counts of every page`() = runTest {
        val requests = mutableListOf<QueryRequest>()
        coEvery { dynamoDbClient.query(capture(requests)) } returnsMany listOf(
            QueryResponse {
                count = 7
                lastEvaluatedKey = mapOf("id" to AttributeValue.S("n-7"))
            },
            QueryResponse {
                count = 3
                lastEvaluatedKey = null
            },
        )

        assertEquals(10, repository.getUnreadCount("user-1"))
        assertEquals("#r = :readVal", requests[0].filterExpression)
        assertEquals(mapOf("#r" to "read"), requests[0].expressionAttributeNames)
        assertEquals(
            AttributeValue.Bool(false),
            requests[1].expressionAttributeValues?.get(":readVal"),
        )
        assertEquals(mapOf("id" to AttributeValue.S("n-7")), requests[1].exclusiveStartKey)
    }

    @Test
    fun `markAsRead updates the read flag and reports success`() = runTest {
        val request = slot<UpdateItemRequest>()
        coEvery { dynamoDbClient.updateItem(capture(request)) } returns UpdateItemResponse { }

        assertTrue(repository.markAsRead("n-1"))
        assertEquals("test-notifications", request.captured.tableName)
        assertEquals("SET #r = :readVal", request.captured.updateExpression)
        assertEquals("attribute_exists(id)", request.captured.conditionExpression)
        assertEquals(
            AttributeValue.Bool(true),
            request.captured.expressionAttributeValues?.get(":readVal"),
        )
    }

    @Test
    fun `markAsRead reports failure when the conditional update is rejected`() = runTest {
        coEvery { dynamoDbClient.updateItem(any()) } throws RuntimeException("conditional check failed")

        assertFalse(repository.markAsRead("missing"))
    }

    @Test
    fun `markAllAsRead only updates the unread notifications`() = runTest {
        coEvery { dynamoDbClient.query(any()) } returns QueryResponse {
            items = listOf(
                notificationItem("n-1", read = false),
                notificationItem("n-2", read = true),
                notificationItem("n-3", read = false),
            )
            count = 3
            lastEvaluatedKey = null
        }
        val updated = mutableListOf<UpdateItemRequest>()
        coEvery { dynamoDbClient.updateItem(capture(updated)) } returns UpdateItemResponse { }

        assertEquals(2, repository.markAllAsRead("user-1"))
        assertEquals(
            listOf(AttributeValue.S("n-1"), AttributeValue.S("n-3")),
            updated.map { it.key!!.getValue("id") },
        )
    }

    @Test
    fun `markAllAsRead returns zero when nothing is unread`() = runTest {
        coEvery { dynamoDbClient.query(any()) } returns QueryResponse {
            items = listOf(notificationItem("n-1", read = true))
            count = 1
            lastEvaluatedKey = null
        }

        assertEquals(0, repository.markAllAsRead("user-1"))
        coVerify(exactly = 0) { dynamoDbClient.updateItem(any()) }
    }

    @Test
    fun `deleteNotification deletes by id and reports success`() = runTest {
        val request = slot<DeleteItemRequest>()
        coEvery { dynamoDbClient.deleteItem(capture(request)) } returns DeleteItemResponse { }

        assertTrue(repository.deleteNotification("n-1"))
        assertEquals("test-notifications", request.captured.tableName)
        assertEquals(mapOf("id" to AttributeValue.S("n-1")), request.captured.key)
    }

    @Test
    fun `deleteNotification reports failure when DynamoDB rejects the delete`() = runTest {
        coEvery { dynamoDbClient.deleteItem(any()) } throws RuntimeException("throttled")

        assertFalse(repository.deleteNotification("n-1"))
    }

    @Test
    fun `getPreferences maps stored channels`() = runTest {
        val request = slot<GetItemRequest>()
        coEvery { dynamoDbClient.getItem(capture(request)) } returns GetItemResponse {
            item = mapOf(
                "userId" to AttributeValue.S("user-1"),
                "channels" to AttributeValue.M(
                    mapOf(
                        "file_shared" to AttributeValue.L(
                            listOf(AttributeValue.S("EMAIL"), AttributeValue.S("IN_APP")),
                        ),
                    ),
                ),
            )
        }

        val preferences = repository.getPreferences("user-1")

        assertEquals("user-1", preferences.userId)
        assertEquals(
            mapOf("file_shared" to listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP)),
            preferences.channels,
        )
        assertEquals("test-preferences", request.captured.tableName)
    }

    @Test
    fun `getPreferences drops unknown and malformed channel entries`() = runTest {
        coEvery { dynamoDbClient.getItem(any()) } returns GetItemResponse {
            item = mapOf(
                "userId" to AttributeValue.S("user-1"),
                "channels" to AttributeValue.M(
                    mapOf(
                        "file_shared" to AttributeValue.L(
                            listOf(
                                AttributeValue.S("EMAIL"),
                                AttributeValue.S("CARRIER_PIGEON"),
                                AttributeValue.N("7"),
                            ),
                        ),
                        "comment_added" to AttributeValue.S("not-a-list"),
                    ),
                ),
            )
        }

        val preferences = repository.getPreferences("user-1")

        assertEquals(listOf(DeliveryChannel.EMAIL), preferences.channels["file_shared"])
        assertEquals(emptyList(), preferences.channels["comment_added"])
    }

    @Test
    fun `getPreferences falls back to defaults when nothing is stored`() = runTest {
        coEvery { dynamoDbClient.getItem(any()) } returns GetItemResponse { item = null }

        val preferences = repository.getPreferences("user-1")

        assertEquals(NotificationPreference(userId = "user-1"), preferences)
        assertTrue(DeliveryChannel.EMAIL in preferences.channels.getValue("file_shared"))
    }

    @Test
    fun `getPreferences falls back to defaults when the stored item has no userId`() = runTest {
        coEvery { dynamoDbClient.getItem(any()) } returns GetItemResponse {
            item = mapOf("channels" to AttributeValue.M(emptyMap()))
        }

        assertEquals(NotificationPreference(userId = "user-1"), repository.getPreferences("user-1"))
    }

    @Test
    fun `getPreferences yields no channels when the channels attribute is missing`() = runTest {
        coEvery { dynamoDbClient.getItem(any()) } returns GetItemResponse {
            item = mapOf("userId" to AttributeValue.S("user-1"))
        }

        assertEquals(emptyMap(), repository.getPreferences("user-1").channels)
    }

    @Test
    fun `savePreferences persists the channel names per event type`() = runTest {
        val request = slot<PutItemRequest>()
        coEvery { dynamoDbClient.putItem(capture(request)) } returns PutItemResponse { }

        repository.savePreferences(
            NotificationPreference(
                userId = "user-1",
                channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH)),
            )
        )

        val item = request.captured.item!!
        assertEquals("test-preferences", request.captured.tableName)
        assertEquals(AttributeValue.S("user-1"), item["userId"])
        assertEquals(
            AttributeValue.M(
                mapOf(
                    "file_shared" to AttributeValue.L(
                        listOf(AttributeValue.S("EMAIL"), AttributeValue.S("PUSH")),
                    ),
                ),
            ),
            item["channels"],
        )
    }
}
