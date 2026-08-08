package com.otterworks.notification.repository

import aws.sdk.kotlin.services.dynamodb.DynamoDbClient
import aws.sdk.kotlin.services.dynamodb.model.AttributeValue
import aws.sdk.kotlin.services.dynamodb.model.ConditionalCheckFailedException
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
import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.notification
import com.otterworks.notification.testConfig
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

    private val dynamoDb = mockk<DynamoDbClient>()
    private val config = testConfig()
    private val repository = NotificationRepository(dynamoDb, config)

    private fun item(
        id: String = "n-1",
        userId: String = "user-1",
        read: Boolean = false,
        extra: Map<String, AttributeValue> = emptyMap(),
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
    ) + extra

    // ---------- saveNotification ----------

    @Test
    fun `saveNotification writes every field to the notifications table`() = runTest {
        val request = slot<PutItemRequest>()
        coEvery { dynamoDb.putItem(capture(request)) } returns PutItemResponse {}

        repository.saveNotification(notification(deliveredVia = listOf("in_app", "email")))

        val written = request.captured
        assertEquals("test-notifications", written.tableName)
        val item = assertNotNull(written.item)
        assertEquals(AttributeValue.S("n-1"), item["id"])
        assertEquals(AttributeValue.S("user-1"), item["userId"])
        assertEquals(AttributeValue.S("file_shared"), item["type"])
        assertEquals(AttributeValue.S("actor-1"), item["actorId"])
        assertEquals(AttributeValue.Bool(false), item["read"])
        assertEquals(
            listOf(AttributeValue.S("in_app"), AttributeValue.S("email")),
            (item["deliveredVia"] as AttributeValue.L).value,
        )
        assertEquals(AttributeValue.S("2024-01-01T00:00:00Z"), item["createdAt"])
    }

    // ---------- getNotificationById ----------

    @Test
    fun `getNotificationById maps a stored item back into a Notification`() = runTest {
        val request = slot<GetItemRequest>()
        coEvery { dynamoDb.getItem(capture(request)) } returns GetItemResponse { item = item(read = true) }

        val found = assertNotNull(repository.getNotificationById("n-1"))

        assertEquals("test-notifications", request.captured.tableName)
        assertEquals(mapOf("id" to AttributeValue.S("n-1")), request.captured.key)
        assertEquals("n-1", found.id)
        assertEquals("user-1", found.userId)
        assertEquals("file", found.resourceType)
        assertTrue(found.read)
        assertEquals(listOf("in_app"), found.deliveredVia)
    }

    @Test
    fun `getNotificationById returns null when the item does not exist`() = runTest {
        coEvery { dynamoDb.getItem(any()) } returns GetItemResponse {}

        assertNull(repository.getNotificationById("missing"))
    }

    @Test
    fun `getNotificationById returns null when the stored item has no id or userId`() = runTest {
        coEvery { dynamoDb.getItem(any()) } returns GetItemResponse {
            item = mapOf("userId" to AttributeValue.S("user-1"))
        }
        assertNull(repository.getNotificationById("n-1"))

        coEvery { dynamoDb.getItem(any()) } returns GetItemResponse {
            item = mapOf("id" to AttributeValue.S("n-1"))
        }
        assertNull(repository.getNotificationById("n-1"))
    }

    @Test
    fun `getNotificationById defaults optional attributes that are absent or wrongly typed`() = runTest {
        coEvery { dynamoDb.getItem(any()) } returns GetItemResponse {
            item = mapOf(
                "id" to AttributeValue.S("n-2"),
                "userId" to AttributeValue.S("user-9"),
                "read" to AttributeValue.S("not-a-bool"),
                "deliveredVia" to AttributeValue.L(
                    listOf(AttributeValue.S("email"), AttributeValue.Bool(true)),
                ),
            )
        }

        val found = assertNotNull(repository.getNotificationById("n-2"))

        assertEquals("", found.type)
        assertEquals("", found.title)
        assertEquals("", found.message)
        assertEquals("", found.resourceId)
        assertEquals("", found.resourceType)
        assertEquals("", found.actorId)
        assertEquals("", found.createdAt)
        assertFalse(found.read)
        assertEquals(listOf("email"), found.deliveredVia)
    }

    // ---------- getNotificationsByUserId ----------

    @Test
    fun `getNotificationsByUserId follows pagination tokens and queries the GSI newest-first`() = runTest {
        val requests = mutableListOf<QueryRequest>()
        coEvery { dynamoDb.query(capture(requests)) } returnsMany listOf(
            QueryResponse {
                items = listOf(item(id = "n-1"), item(id = "n-2"))
                lastEvaluatedKey = mapOf("id" to AttributeValue.S("n-2"))
            },
            QueryResponse { items = listOf(item(id = "n-3")) },
        )

        val (page, total) = repository.getNotificationsByUserId("user-1", page = 1, pageSize = 20)

        assertEquals(3, total)
        assertEquals(listOf("n-1", "n-2", "n-3"), page.map { it.id })
        assertEquals(2, requests.size)
        assertEquals("userId-createdAt-index", requests[0].indexName)
        assertEquals("userId = :uid", requests[0].keyConditionExpression)
        assertEquals(false, requests[0].scanIndexForward)
        assertEquals(mapOf(":uid" to AttributeValue.S("user-1")), requests[0].expressionAttributeValues)
        assertNull(requests[0].exclusiveStartKey)
        assertEquals(mapOf("id" to AttributeValue.S("n-2")), requests[1].exclusiveStartKey)
    }

    @Test
    fun `getNotificationsByUserId slices the requested page out of the full result set`() = runTest {
        coEvery { dynamoDb.query(any()) } returns QueryResponse {
            items = (1..5).map { item(id = "n-$it") }
        }

        val (secondPage, total) = repository.getNotificationsByUserId("user-1", page = 2, pageSize = 2)

        assertEquals(5, total)
        assertEquals(listOf("n-3", "n-4"), secondPage.map { it.id })
    }

    @Test
    fun `getNotificationsByUserId skips unmappable items and tolerates an empty result`() = runTest {
        coEvery { dynamoDb.query(any()) } returns QueryResponse {
            items = listOf(item(id = "n-1"), mapOf("userId" to AttributeValue.S("user-1")))
        }

        val (withBadItem, totalWithBadItem) = repository.getNotificationsByUserId("user-1")
        assertEquals(listOf("n-1"), withBadItem.map { it.id })
        assertEquals(1, totalWithBadItem)

        coEvery { dynamoDb.query(any()) } returns QueryResponse {}
        val (empty, total) = repository.getNotificationsByUserId("user-1")
        assertEquals(emptyList(), empty)
        assertEquals(0, total)
    }

    // ---------- getUnreadCount ----------

    @Test
    fun `getUnreadCount sums counts across pages and filters on the read flag`() = runTest {
        val requests = mutableListOf<QueryRequest>()
        coEvery { dynamoDb.query(capture(requests)) } returnsMany listOf(
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
        assertNull(requests[0].exclusiveStartKey)
        assertEquals(mapOf("id" to AttributeValue.S("n-2")), requests[1].exclusiveStartKey)
    }

    // ---------- markAsRead / markAllAsRead ----------

    @Test
    fun `markAsRead issues a conditional update and reports success`() = runTest {
        val request = slot<UpdateItemRequest>()
        coEvery { dynamoDb.updateItem(capture(request)) } returns UpdateItemResponse {}

        assertTrue(repository.markAsRead("n-1"))

        val captured = request.captured
        assertEquals("test-notifications", captured.tableName)
        assertEquals(mapOf("id" to AttributeValue.S("n-1")), captured.key)
        assertEquals("SET #r = :readVal", captured.updateExpression)
        assertEquals("attribute_exists(id)", captured.conditionExpression)
        assertEquals(AttributeValue.Bool(true), captured.expressionAttributeValues?.get(":readVal"))
    }

    @Test
    fun `markAsRead returns false when the conditional update fails`() = runTest {
        coEvery { dynamoDb.updateItem(any()) } throws ConditionalCheckFailedException { message = "no such item" }

        assertFalse(repository.markAsRead("missing"))
    }

    @Test
    fun `markAllAsRead only updates the unread notifications and returns how many`() = runTest {
        coEvery { dynamoDb.query(any()) } returns QueryResponse {
            items = listOf(
                item(id = "n-1", read = false),
                item(id = "n-2", read = true),
                item(id = "n-3", read = false),
            )
        }
        coEvery { dynamoDb.updateItem(any()) } returns UpdateItemResponse {}

        assertEquals(2, repository.markAllAsRead("user-1"))

        coVerify(exactly = 1) { dynamoDb.updateItem(match { it.key?.get("id") == AttributeValue.S("n-1") }) }
        coVerify(exactly = 1) { dynamoDb.updateItem(match { it.key?.get("id") == AttributeValue.S("n-3") }) }
        coVerify(exactly = 0) { dynamoDb.updateItem(match { it.key?.get("id") == AttributeValue.S("n-2") }) }
    }

    @Test
    fun `markAllAsRead returns zero when the user has nothing unread`() = runTest {
        coEvery { dynamoDb.query(any()) } returns QueryResponse {
            items = listOf(item(id = "n-1", read = true))
        }

        assertEquals(0, repository.markAllAsRead("user-1"))

        coVerify(exactly = 0) { dynamoDb.updateItem(any()) }
    }

    // ---------- deleteNotification ----------

    @Test
    fun `deleteNotification deletes by primary key`() = runTest {
        val request = slot<DeleteItemRequest>()
        coEvery { dynamoDb.deleteItem(capture(request)) } returns DeleteItemResponse {}

        assertTrue(repository.deleteNotification("n-1"))

        assertEquals("test-notifications", request.captured.tableName)
        assertEquals(mapOf("id" to AttributeValue.S("n-1")), request.captured.key)
    }

    @Test
    fun `deleteNotification returns false when DynamoDB rejects the delete`() = runTest {
        coEvery { dynamoDb.deleteItem(any()) } throws IllegalStateException("boom")

        assertFalse(repository.deleteNotification("n-1"))
    }

    // ---------- preferences ----------

    @Test
    fun `getPreferences maps stored channels and drops unknown channel names`() = runTest {
        val request = slot<GetItemRequest>()
        coEvery { dynamoDb.getItem(capture(request)) } returns GetItemResponse {
            item = mapOf(
                "userId" to AttributeValue.S("user-1"),
                "channels" to AttributeValue.M(
                    mapOf(
                        "file_shared" to AttributeValue.L(
                            listOf(
                                AttributeValue.S("EMAIL"),
                                AttributeValue.S("CARRIER_PIGEON"),
                                AttributeValue.Bool(true),
                            ),
                        ),
                        "comment_added" to AttributeValue.S("not-a-list"),
                    ),
                ),
            )
        }

        val preferences = repository.getPreferences("user-1")

        assertEquals("test-preferences", request.captured.tableName)
        assertEquals(mapOf("userId" to AttributeValue.S("user-1")), request.captured.key)
        assertEquals(listOf(DeliveryChannel.EMAIL), preferences.channels["file_shared"])
        assertEquals(emptyList(), preferences.channels["comment_added"])
    }

    @Test
    fun `getPreferences falls back to the defaults when nothing is stored`() = runTest {
        coEvery { dynamoDb.getItem(any()) } returns GetItemResponse {}

        val preferences = repository.getPreferences("user-1")

        assertEquals("user-1", preferences.userId)
        assertEquals(
            listOf(DeliveryChannel.EMAIL, DeliveryChannel.IN_APP, DeliveryChannel.PUSH),
            preferences.channels["file_shared"],
        )
        assertEquals(listOf(DeliveryChannel.IN_APP), preferences.channels["document_edited"])
    }

    @Test
    fun `getPreferences falls back to the defaults when the stored item has no userId`() = runTest {
        coEvery { dynamoDb.getItem(any()) } returns GetItemResponse {
            item = mapOf("channels" to AttributeValue.M(emptyMap()))
        }

        val preferences = repository.getPreferences("user-1")

        assertEquals("user-1", preferences.userId)
        assertEquals(4, preferences.channels.size)
    }

    @Test
    fun `getPreferences yields no channels when the stored channels attribute is missing`() = runTest {
        coEvery { dynamoDb.getItem(any()) } returns GetItemResponse {
            item = mapOf("userId" to AttributeValue.S("user-1"))
        }

        assertEquals(emptyMap(), repository.getPreferences("user-1").channels)
    }

    @Test
    fun `savePreferences flattens channels into a DynamoDB map attribute`() = runTest {
        val request = slot<PutItemRequest>()
        coEvery { dynamoDb.putItem(capture(request)) } returns PutItemResponse {}

        repository.savePreferences(
            NotificationPreference(
                userId = "user-1",
                channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH)),
            ),
        )

        val item = assertNotNull(request.captured.item)
        assertEquals("test-preferences", request.captured.tableName)
        assertEquals(AttributeValue.S("user-1"), item["userId"])
        assertEquals(
            AttributeValue.L(listOf(AttributeValue.S("EMAIL"), AttributeValue.S("PUSH"))),
            (item["channels"] as AttributeValue.M).value["file_shared"],
        )
    }
}
