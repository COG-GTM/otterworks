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
import com.otterworks.notification.config.AppConfig
import com.otterworks.notification.model.DeliveryChannel
import com.otterworks.notification.model.Notification
import com.otterworks.notification.model.NotificationPreference
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
import kotlinx.coroutines.test.runTest
import org.junit.Ignore
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class NotificationRepositoryQaTest {

    private val dynamo = mockk<DynamoDbClient>()
    private val config = AppConfig(
        port = 8086,
        awsRegion = "us-east-1",
        awsEndpointUrl = null,
        sqsQueueUrl = "q",
        snsTopicArn = "t",
        dynamoDbTableNotifications = "notif-table",
        dynamoDbTablePreferences = "pref-table",
        sesFromEmail = "from@otterworks.io",
        sqsPollIntervalMs = 10,
        sqsMaxMessages = 1,
        sqsWaitTimeSeconds = 0,
    )
    private val repo = NotificationRepository(dynamo, config)

    private fun item(id: String, userId: String = "u1", read: Boolean = false, createdAt: String = "2026-01-01T00:00:0${id.last()}Z") =
        mapOf(
            "id" to AttributeValue.S(id),
            "userId" to AttributeValue.S(userId),
            "type" to AttributeValue.S("file_shared"),
            "title" to AttributeValue.S("t"),
            "message" to AttributeValue.S("m"),
            "read" to AttributeValue.Bool(read),
            "deliveredVia" to AttributeValue.L(listOf(AttributeValue.S("in_app"))),
            "createdAt" to AttributeValue.S(createdAt),
        )

    private fun items(n: Int) = (1..n).map { item("n$it") }

    @Test
    fun `saveNotification writes every attribute to the notifications table`() = runTest {
        val captured = slot<PutItemRequest>()
        coEvery { dynamo.putItem(capture(captured)) } returns PutItemResponse {}
        repo.saveNotification(
            Notification(
                id = "n1", userId = "u1", type = "file_shared", title = "T", message = "M",
                resourceId = "f1", resourceType = "file", actorId = "a1", read = false,
                deliveredVia = listOf("in_app", "email"), createdAt = "2026-01-01T00:00:00Z",
            )
        )
        assertEquals("notif-table", captured.captured.tableName)
        val it = captured.captured.item!!
        assertEquals("u1", (it["userId"] as AttributeValue.S).value)
        assertEquals(false, (it["read"] as AttributeValue.Bool).value)
        assertEquals(2, (it["deliveredVia"] as AttributeValue.L).value.size)
    }

    @Test
    fun `getNotificationById maps item and returns null for missing`() = runTest {
        coEvery { dynamo.getItem(match<GetItemRequest> { (it.key!!["id"] as AttributeValue.S).value == "n1" }) } returns
            GetItemResponse { item = item("n1", read = true) }
        coEvery { dynamo.getItem(match<GetItemRequest> { (it.key!!["id"] as AttributeValue.S).value == "nope" }) } returns
            GetItemResponse { item = null }
        val n = repo.getNotificationById("n1")!!
        assertEquals("u1", n.userId)
        assertTrue(n.read)
        assertEquals(listOf("in_app"), n.deliveredVia)
        assertNull(repo.getNotificationById("nope"))
    }

    @Test
    fun `items missing userId are dropped by the mapper`() = runTest {
        coEvery { dynamo.getItem(any()) } returns GetItemResponse { item = mapOf("id" to AttributeValue.S("x")) }
        assertNull(repo.getNotificationById("x"))
    }

    @Test
    fun `getNotificationsByUserId queries GSI newest-first and slices the page`() = runTest {
        val req = slot<QueryRequest>()
        coEvery { dynamo.query(capture(req)) } returns QueryResponse { this.items = items(5); count = 5 }
        val (page2, total) = repo.getNotificationsByUserId("u1", page = 2, pageSize = 2)
        assertEquals(5, total)
        assertEquals(listOf("n3", "n4"), page2.map { it.id })
        assertEquals("userId-createdAt-index", req.captured.indexName)
        assertEquals(false, req.captured.scanIndexForward)
    }

    @Test
    fun `getNotificationsByUserId follows LastEvaluatedKey across query pages`() = runTest {
        coEvery { dynamo.query(match { it.exclusiveStartKey == null }) } returns QueryResponse {
            this.items = items(2); count = 2; lastEvaluatedKey = mapOf("id" to AttributeValue.S("n2"))
        }
        coEvery { dynamo.query(match { it.exclusiveStartKey != null }) } returns QueryResponse {
            this.items = listOf(item("n3")); count = 1
        }
        val (all, total) = repo.getNotificationsByUserId("u1", 1, 50)
        assertEquals(3, total)
        assertEquals(3, all.size)
        coVerify(exactly = 2) { dynamo.query(any()) }
    }

    @Test
    fun `page beyond the end returns an empty slice but real total`() = runTest {
        coEvery { dynamo.query(any()) } returns QueryResponse { this.items = items(3); count = 3 }
        val (page, total) = repo.getNotificationsByUserId("u1", page = 5, pageSize = 2)
        assertTrue(page.isEmpty())
        assertEquals(3, total)
    }

    @Ignore("FINDING NS-4: page=0 makes startIndex negative and List.drop throws IllegalArgumentException (500 at the API)")
    @Test
    fun `page zero is clamped to the first page`() = runTest {
        coEvery { dynamo.query(any()) } returns QueryResponse { this.items = items(3); count = 3 }
        val (page, _) = repo.getNotificationsByUserId("u1", page = 0, pageSize = 2)
        assertEquals(2, page.size)
    }

    @Test
    fun `getUnreadCount sums filtered counts across pages`() = runTest {
        val req = mutableListOf<QueryRequest>()
        coEvery { dynamo.query(capture(req)) } returnsMany listOf(
            QueryResponse { count = 2; lastEvaluatedKey = mapOf("id" to AttributeValue.S("k")) },
            QueryResponse { count = 1 },
        )
        assertEquals(3, repo.getUnreadCount("u1"))
        assertEquals("#r = :readVal", req.first().filterExpression)
    }

    @Test
    fun `markAsRead is conditional on existence and reports failure as false`() = runTest {
        val req = slot<UpdateItemRequest>()
        coEvery { dynamo.updateItem(capture(req)) } returns UpdateItemResponse {}
        assertTrue(repo.markAsRead("n1"))
        assertEquals("attribute_exists(id)", req.captured.conditionExpression)

        coEvery { dynamo.updateItem(any()) } throws ConditionalCheckFailedException {}
        assertFalse(repo.markAsRead("missing"))
    }

    @Test
    fun `markAllAsRead only updates unread notifications and returns their count`() = runTest {
        coEvery { dynamo.query(any()) } returns QueryResponse {
            this.items = listOf(item("n1"), item("n2", read = true), item("n3")); count = 3
        }
        coEvery { dynamo.updateItem(any()) } returns UpdateItemResponse {}
        assertEquals(2, repo.markAllAsRead("u1"))
        coVerify(exactly = 2) { dynamo.updateItem(any()) }
    }

    @Ignore("FINDING NS-8: markAllAsRead ignores markAsRead failures and still reports them in markedCount")
    @Test
    fun `markAllAsRead count excludes failed updates`() = runTest {
        coEvery { dynamo.query(any()) } returns QueryResponse { this.items = listOf(item("n1"), item("n2")); count = 2 }
        coEvery { dynamo.updateItem(any()) } throws RuntimeException("throttled")
        assertEquals(0, repo.markAllAsRead("u1"))
    }

    @Test
    fun `deleteNotification returns true on success and false on error`() = runTest {
        coEvery { dynamo.deleteItem(any()) } returns DeleteItemResponse {}
        assertTrue(repo.deleteNotification("n1"))
        coEvery { dynamo.deleteItem(any<DeleteItemRequest>()) } throws RuntimeException("boom")
        assertFalse(repo.deleteNotification("n1"))
    }

    @Ignore("FINDING NS-13: deleteNotification is unconditional, so DELETE of a nonexistent id returns 204 instead of 404")
    @Test
    fun `deleteNotification is conditional on existence`() = runTest {
        val req = slot<DeleteItemRequest>()
        coEvery { dynamo.deleteItem(capture(req)) } returns DeleteItemResponse {}
        repo.deleteNotification("n1")
        assertEquals("attribute_exists(id)", req.captured.conditionExpression)
    }

    @Test
    fun `getPreferences falls back to defaults when no row exists`() = runTest {
        coEvery { dynamo.getItem(any()) } returns GetItemResponse { item = null }
        val prefs = repo.getPreferences("u1")
        assertEquals(NotificationPreference(userId = "u1"), prefs)
    }

    @Test
    fun `getPreferences skips unknown channel names`() = runTest {
        coEvery { dynamo.getItem(any()) } returns GetItemResponse {
            item = mapOf(
                "userId" to AttributeValue.S("u1"),
                "channels" to AttributeValue.M(
                    mapOf("file_shared" to AttributeValue.L(listOf(AttributeValue.S("EMAIL"), AttributeValue.S("SMS"))))
                ),
            )
        }
        assertEquals(mapOf("file_shared" to listOf(DeliveryChannel.EMAIL)), repo.getPreferences("u1").channels)
    }

    @Test
    fun `savePreferences serialises channel enum names to the preferences table`() = runTest {
        val req = slot<PutItemRequest>()
        coEvery { dynamo.putItem(capture(req)) } returns PutItemResponse {}
        repo.savePreferences(NotificationPreference("u1", mapOf("document_edited" to listOf(DeliveryChannel.PUSH))))
        assertEquals("pref-table", req.captured.tableName)
        val channels = (req.captured.item!!["channels"] as AttributeValue.M).value
        assertEquals(listOf("PUSH"), (channels["document_edited"] as AttributeValue.L).value.map { (it as AttributeValue.S).value })
    }
}
