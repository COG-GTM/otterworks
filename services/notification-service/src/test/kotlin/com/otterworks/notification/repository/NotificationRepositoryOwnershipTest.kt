package com.otterworks.notification.repository

import aws.sdk.kotlin.services.dynamodb.DynamoDbClient
import aws.sdk.kotlin.services.dynamodb.model.AttributeValue
import aws.sdk.kotlin.services.dynamodb.model.ConditionalCheckFailedException
import aws.sdk.kotlin.services.dynamodb.model.DeleteItemRequest
import aws.sdk.kotlin.services.dynamodb.model.DeleteItemResponse
import aws.sdk.kotlin.services.dynamodb.model.GetItemResponse
import aws.sdk.kotlin.services.dynamodb.model.QueryResponse
import aws.sdk.kotlin.services.dynamodb.model.UpdateItemRequest
import aws.sdk.kotlin.services.dynamodb.model.UpdateItemResponse
import com.otterworks.notification.config.AppConfig
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

class NotificationRepositoryOwnershipTest {

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

    private fun item(id: String, owner: String, read: Boolean = false) = mapOf(
        "id" to AttributeValue.S(id),
        "userId" to AttributeValue.S(owner),
        "type" to AttributeValue.S("file_shared"),
        "title" to AttributeValue.S("File Shared With You"),
        "message" to AttributeValue.S("secret.pdf"),
        "read" to AttributeValue.Bool(read),
        "createdAt" to AttributeValue.S("2024-01-01T00:00:00Z"),
    )

    @Test
    fun `getNotificationById returns the item to its owner`() = runTest {
        coEvery { dynamoDbClient.getItem(any()) } returns GetItemResponse { item = item("n-1", "victim") }

        val notification = repository.getNotificationById("n-1", "victim")

        assertNotNull(notification)
        assertEquals("n-1", notification.id)
    }

    @Test
    fun `getNotificationById hides another user's item`() = runTest {
        coEvery { dynamoDbClient.getItem(any()) } returns GetItemResponse { item = item("n-1", "victim") }

        assertNull(repository.getNotificationById("n-1", "attacker"))
    }

    @Test
    fun `markAsRead conditions the update on the caller owning the item`() = runTest {
        val request = slot<UpdateItemRequest>()
        coEvery { dynamoDbClient.updateItem(capture(request)) } returns UpdateItemResponse {}

        assertTrue(repository.markAsRead("n-1", "victim"))

        assertEquals("attribute_exists(id) AND userId = :uid", request.captured.conditionExpression)
        assertEquals(AttributeValue.S("victim"), request.captured.expressionAttributeValues?.get(":uid"))
        assertEquals(AttributeValue.S("n-1"), request.captured.key?.get("id"))
    }

    @Test
    fun `markAsRead returns false when the ownership condition fails`() = runTest {
        coEvery { dynamoDbClient.updateItem(any()) } throws ConditionalCheckFailedException { message = "The conditional request failed" }

        assertFalse(repository.markAsRead("n-1", "attacker"))
    }

    @Test
    fun `deleteNotification conditions the delete on the caller owning the item`() = runTest {
        val request = slot<DeleteItemRequest>()
        coEvery { dynamoDbClient.deleteItem(capture(request)) } returns DeleteItemResponse {}

        assertTrue(repository.deleteNotification("n-1", "victim"))

        assertEquals("userId = :uid", request.captured.conditionExpression)
        assertEquals(AttributeValue.S("victim"), request.captured.expressionAttributeValues?.get(":uid"))
        assertEquals(AttributeValue.S("n-1"), request.captured.key?.get("id"))
    }

    @Test
    fun `deleteNotification returns false when the ownership condition fails`() = runTest {
        coEvery { dynamoDbClient.deleteItem(any()) } throws ConditionalCheckFailedException { message = "The conditional request failed" }

        assertFalse(repository.deleteNotification("n-1", "attacker"))
    }

    @Test
    fun `markAllAsRead marks the caller's unread items under the caller's id`() = runTest {
        coEvery { dynamoDbClient.query(any()) } returns QueryResponse {
            items = listOf(item("n-1", "victim"), item("n-2", "victim", read = true))
            count = 2
        }
        val request = slot<UpdateItemRequest>()
        coEvery { dynamoDbClient.updateItem(capture(request)) } returns UpdateItemResponse {}

        assertEquals(1, repository.markAllAsRead("victim"))

        coVerify(exactly = 1) { dynamoDbClient.updateItem(any()) }
        assertEquals(AttributeValue.S("victim"), request.captured.expressionAttributeValues?.get(":uid"))
    }
}
