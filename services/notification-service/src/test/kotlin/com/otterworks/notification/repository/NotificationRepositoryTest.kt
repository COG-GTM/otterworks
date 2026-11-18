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
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import com.otterworks.notification.testConfig
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

    private val client = mockk<DynamoDbClient>()
    private val repository = NotificationRepository(client, testConfig())

    private fun item(id: String, userId: String = "u1", read: Boolean = false) = mapOf(
        "id" to AttributeValue.S(id),
        "userId" to AttributeValue.S(userId),
        "type" to AttributeValue.S("file_shared"),
        "title" to AttributeValue.S("t"),
        "message" to AttributeValue.S("m"),
        "resourceId" to AttributeValue.S("r"),
        "resourceType" to AttributeValue.S("file"),
        "actorId" to AttributeValue.S("a"),
        "read" to AttributeValue.Bool(read),
        "deliveredVia" to AttributeValue.L(listOf(AttributeValue.S("in_app"), AttributeValue.N("1"))),
        "createdAt" to AttributeValue.S("2024-01-01T00:00:00Z"),
    )

    @Test
    fun `saveNotification writes all attributes to the notifications table`() = runTest {
        val captured = slot<PutItemRequest>()
        coEvery { client.putItem(capture(captured)) } returns PutItemResponse {}

        repository.saveNotification(
            Notification(
                id = "n1", userId = "u1", type = "file_shared", title = "t", message = "m",
                resourceId = "r", resourceType = "file", actorId = "a", read = true,
                deliveredVia = listOf("in_app", "email"), createdAt = "2024-01-01T00:00:00Z",
            )
        )

        val req = captured.captured
        assertEquals("test-notifications", req.tableName)
        val i = req.item!!
        assertEquals(AttributeValue.S("n1"), i["id"])
        assertEquals(AttributeValue.S("u1"), i["userId"])
        assertEquals(AttributeValue.Bool(true), i["read"])
        assertEquals(
            AttributeValue.L(listOf(AttributeValue.S("in_app"), AttributeValue.S("email"))),
            i["deliveredVia"],
        )
        assertEquals(AttributeValue.S("2024-01-01T00:00:00Z"), i["createdAt"])
    }

    @Test
    fun `getNotificationById maps a full item`() = runTest {
        val captured = slot<GetItemRequest>()
        coEvery { client.getItem(capture(captured)) } returns GetItemResponse { item = item("n1", read = true) }

        val n = repository.getNotificationById("n1")!!

        assertEquals("test-notifications", captured.captured.tableName)
        assertEquals(mapOf("id" to AttributeValue.S("n1")), captured.captured.key)
        assertEquals("n1", n.id)
        assertEquals("u1", n.userId)
        assertEquals("file_shared", n.type)
        assertEquals("t", n.title)
        assertEquals("m", n.message)
        assertEquals("r", n.resourceId)
        assertEquals("file", n.resourceType)
        assertEquals("a", n.actorId)
        assertTrue(n.read)
        assertEquals(listOf("in_app"), n.deliveredVia)
        assertEquals("2024-01-01T00:00:00Z", n.createdAt)
    }

    @Test
    fun `getNotificationById returns null when item missing`() = runTest {
        coEvery { client.getItem(any<GetItemRequest>()) } returns GetItemResponse {}
        assertNull(repository.getNotificationById("missing"))
    }

    @Test
    fun `getNotificationById returns null when required keys are missing`() = runTest {
        coEvery { client.getItem(any<GetItemRequest>()) } returns
            GetItemResponse { item = mapOf("userId" to AttributeValue.S("u1")) }
        assertNull(repository.getNotificationById("x"))

        coEvery { client.getItem(any<GetItemRequest>()) } returns
            GetItemResponse { item = mapOf("id" to AttributeValue.S("x")) }
        assertNull(repository.getNotificationById("x"))
    }

    @Test
    fun `getNotificationById defaults optional attributes`() = runTest {
        coEvery { client.getItem(any<GetItemRequest>()) } returns GetItemResponse {
            item = mapOf("id" to AttributeValue.S("x"), "userId" to AttributeValue.S("u1"), "read" to AttributeValue.S("yes"))
        }
        val n = repository.getNotificationById("x")!!
        assertEquals("", n.type)
        assertEquals("", n.title)
        assertEquals("", n.message)
        assertEquals("", n.resourceId)
        assertEquals("", n.resourceType)
        assertEquals("", n.actorId)
        assertFalse(n.read)
        assertEquals(emptyList(), n.deliveredVia)
        assertEquals("", n.createdAt)
    }

    @Test
    fun `getNotificationsByUserId follows pagination keys and pages in memory`() = runTest {
        val requests = mutableListOf<QueryRequest>()
        val lek = mapOf("id" to AttributeValue.S("n2"))
        coEvery { client.query(capture(requests)) } returnsMany listOf(
            QueryResponse { items = listOf(item("n1"), item("n2"), mapOf("bad" to AttributeValue.S("x"))); lastEvaluatedKey = lek },
            QueryResponse { items = listOf(item("n3")) },
        )

        val (page, total) = repository.getNotificationsByUserId("u1", page = 2, pageSize = 2)

        assertEquals(3, total)
        assertEquals(listOf("n3"), page.map { it.id })
        assertEquals(2, requests.size)
        assertEquals("userId-createdAt-index", requests[0].indexName)
        assertEquals("userId = :uid", requests[0].keyConditionExpression)
        assertEquals(AttributeValue.S("u1"), requests[0].expressionAttributeValues!![":uid"])
        assertEquals(false, requests[0].scanIndexForward)
        assertNull(requests[0].exclusiveStartKey)
        assertEquals(lek, requests[1].exclusiveStartKey)
    }

    @Test
    fun `getNotificationsByUserId handles null items`() = runTest {
        coEvery { client.query(any<QueryRequest>()) } returns QueryResponse {}
        val (page, total) = repository.getNotificationsByUserId("u1")
        assertEquals(0, total)
        assertTrue(page.isEmpty())
    }

    @Test
    fun `getUnreadCount sums counts across pages with read filter`() = runTest {
        val requests = mutableListOf<QueryRequest>()
        val lek = mapOf("id" to AttributeValue.S("n2"))
        coEvery { client.query(capture(requests)) } returnsMany listOf(
            QueryResponse { count = 3; lastEvaluatedKey = lek },
            QueryResponse { count = 2 },
        )

        assertEquals(5, repository.getUnreadCount("u1"))
        assertEquals("#r = :readVal", requests[0].filterExpression)
        assertEquals(mapOf("#r" to "read"), requests[0].expressionAttributeNames)
        assertEquals(AttributeValue.Bool(false), requests[0].expressionAttributeValues!![":readVal"])
        assertNull(requests[0].exclusiveStartKey)
        assertEquals(lek, requests[1].exclusiveStartKey)
    }

    @Test
    fun `markAsRead issues conditional update`() = runTest {
        val captured = slot<UpdateItemRequest>()
        coEvery { client.updateItem(capture(captured)) } returns UpdateItemResponse {}

        assertTrue(repository.markAsRead("n1"))
        val req = captured.captured
        assertEquals(mapOf("id" to AttributeValue.S("n1")), req.key)
        assertEquals("SET #r = :readVal", req.updateExpression)
        assertEquals("attribute_exists(id)", req.conditionExpression)
        assertEquals(AttributeValue.Bool(true), req.expressionAttributeValues!![":readVal"])
    }

    @Test
    fun `markAsRead returns false when the condition fails`() = runTest {
        coEvery { client.updateItem(any<UpdateItemRequest>()) } throws
            ConditionalCheckFailedException { message = "missing" }
        assertFalse(repository.markAsRead("missing"))
    }

    @Test
    fun `markAllAsRead marks only unread notifications`() = runTest {
        coEvery { client.query(any<QueryRequest>()) } returns QueryResponse {
            items = listOf(item("n1", read = false), item("n2", read = true), item("n3", read = false))
        }
        val updates = mutableListOf<UpdateItemRequest>()
        coEvery { client.updateItem(capture(updates)) } returns UpdateItemResponse {}

        assertEquals(2, repository.markAllAsRead("u1"))
        assertEquals(
            listOf("n1", "n3"),
            updates.map { (it.key!!["id"] as AttributeValue.S).value },
        )
    }

    @Test
    fun `deleteNotification deletes by id`() = runTest {
        val captured = slot<DeleteItemRequest>()
        coEvery { client.deleteItem(capture(captured)) } returns DeleteItemResponse {}

        assertTrue(repository.deleteNotification("n1"))
        assertEquals("test-notifications", captured.captured.tableName)
        assertEquals(mapOf("id" to AttributeValue.S("n1")), captured.captured.key)
    }

    @Test
    fun `deleteNotification returns false on client error`() = runTest {
        coEvery { client.deleteItem(any<DeleteItemRequest>()) } throws RuntimeException("boom")
        assertFalse(repository.deleteNotification("n1"))
    }

    @Test
    fun `getPreferences returns defaults when no item stored`() = runTest {
        val captured = slot<GetItemRequest>()
        coEvery { client.getItem(capture(captured)) } returns GetItemResponse {}

        assertEquals(NotificationPreference(userId = "u1"), repository.getPreferences("u1"))
        assertEquals("test-preferences", captured.captured.tableName)
        assertEquals(mapOf("userId" to AttributeValue.S("u1")), captured.captured.key)
    }

    @Test
    fun `getPreferences maps stored channels and drops unknown values`() = runTest {
        coEvery { client.getItem(any<GetItemRequest>()) } returns GetItemResponse {
            item = mapOf(
                "userId" to AttributeValue.S("u1"),
                "channels" to AttributeValue.M(
                    mapOf(
                        "file_shared" to AttributeValue.L(
                            listOf(AttributeValue.S("EMAIL"), AttributeValue.S("SMS"), AttributeValue.N("1"))
                        ),
                        "comment_added" to AttributeValue.S("IN_APP"),
                    )
                ),
            )
        }

        val prefs = repository.getPreferences("u1")
        assertEquals(
            mapOf("file_shared" to listOf(DeliveryChannel.EMAIL), "comment_added" to emptyList()),
            prefs.channels,
        )
    }

    @Test
    fun `getPreferences with no channels attribute yields empty map`() = runTest {
        coEvery { client.getItem(any<GetItemRequest>()) } returns
            GetItemResponse { item = mapOf("userId" to AttributeValue.S("u1")) }
        assertEquals(emptyMap(), repository.getPreferences("u1").channels)
    }

    @Test
    fun `getPreferences falls back to defaults when stored item lacks userId`() = runTest {
        coEvery { client.getItem(any<GetItemRequest>()) } returns
            GetItemResponse { item = mapOf("channels" to AttributeValue.M(emptyMap())) }
        assertEquals(NotificationPreference(userId = "u1"), repository.getPreferences("u1"))
    }

    @Test
    fun `savePreferences writes channel map`() = runTest {
        val captured = slot<PutItemRequest>()
        coEvery { client.putItem(capture(captured)) } returns PutItemResponse {}

        repository.savePreferences(
            NotificationPreference(
                userId = "u1",
                channels = mapOf("file_shared" to listOf(DeliveryChannel.EMAIL, DeliveryChannel.PUSH)),
            )
        )

        val req = captured.captured
        assertEquals("test-preferences", req.tableName)
        assertEquals(AttributeValue.S("u1"), req.item!!["userId"])
        assertEquals(
            AttributeValue.M(
                mapOf("file_shared" to AttributeValue.L(listOf(AttributeValue.S("EMAIL"), AttributeValue.S("PUSH"))))
            ),
            req.item!!["channels"],
        )
        coVerify(exactly = 1) { client.putItem(any<PutItemRequest>()) }
    }
}
