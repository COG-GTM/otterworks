package com.otterworks.notification.template

import com.otterworks.notification.model.SqsNotificationMessage

data class RenderedNotification(
    val title: String,
    val message: String,
    val emailSubject: String,
    val emailBody: String,
)

object NotificationTemplates {

    private data class Template(
        val titleTemplate: String,
        val messageTemplate: String,
        val emailSubjectTemplate: String,
        val emailBodyTemplate: String,
    )

    private val templates = mapOf(
        "file_shared" to Template(
            titleTemplate = "File Shared With You",
            messageTemplate = "A file has been shared with you by user {{actorId}}.",
            emailSubjectTemplate = "OtterWorks: A file has been shared with you",
            emailBodyTemplate = """
                <html>
                <body>
                    <h2>File Shared</h2>
                    <p>A file (ID: {{fileId}}) has been shared with you by user {{actorId}}.</p>
                    <p>Log in to OtterWorks to view the file.</p>
                    <br/>
                    <p style="color: #888;">— OtterWorks Notification Service</p>
                </body>
                </html>
            """.trimIndent(),
        ),
        "comment_added" to Template(
            titleTemplate = "New Comment",
            messageTemplate = "A new comment was added by user {{actorId}} on document {{documentId}}.",
            emailSubjectTemplate = "OtterWorks: New comment on your document",
            emailBodyTemplate = """
                <html>
                <body>
                    <h2>New Comment</h2>
                    <p>User {{actorId}} added a comment on document {{documentId}}.</p>
                    <p>Log in to OtterWorks to view the comment.</p>
                    <br/>
                    <p style="color: #888;">— OtterWorks Notification Service</p>
                </body>
                </html>
            """.trimIndent(),
        ),
        "comment_resolved" to Template(
            titleTemplate = "Comment Resolved",
            messageTemplate = "Your comment was resolved by user {{actorId}} on document {{documentId}}.",
            emailSubjectTemplate = "OtterWorks: Your comment was resolved",
            emailBodyTemplate = """
                <html>
                <body>
                    <h2>Comment Resolved</h2>
                    <p>User {{actorId}} resolved your comment on document {{documentId}}.</p>
                    <p>Log in to OtterWorks to view the document.</p>
                    <br/>
                    <p style="color: #888;">— OtterWorks Notification Service</p>
                </body>
                </html>
            """.trimIndent(),
        ),
        "document_edited" to Template(
            titleTemplate = "Document Edited",
            messageTemplate = "Document {{documentId}} was edited by user {{actorId}}.",
            emailSubjectTemplate = "OtterWorks: A document you follow was edited",
            emailBodyTemplate = """
                <html>
                <body>
                    <h2>Document Edited</h2>
                    <p>Document {{documentId}} was edited by user {{actorId}}.</p>
                    <p>Log in to OtterWorks to view the changes.</p>
                    <br/>
                    <p style="color: #888;">— OtterWorks Notification Service</p>
                </body>
                </html>
            """.trimIndent(),
        ),
        "user_mentioned" to Template(
            titleTemplate = "You Were Mentioned",
            messageTemplate = "You were mentioned by user {{actorId}} in document {{documentId}}.",
            emailSubjectTemplate = "OtterWorks: You were mentioned in a document",
            emailBodyTemplate = """
                <html>
                <body>
                    <h2>You Were Mentioned</h2>
                    <p>User {{actorId}} mentioned you in document {{documentId}}.</p>
                    <p>Log in to OtterWorks to see the context.</p>
                    <br/>
                    <p style="color: #888;">— OtterWorks Notification Service</p>
                </body>
                </html>
            """.trimIndent(),
        ),
    )

    fun render(event: SqsNotificationMessage): RenderedNotification {
        val template = templates[event.eventType] ?: return RenderedNotification(
            title = "Notification",
            message = "You have a new notification.",
            emailSubject = "OtterWorks: New notification",
            emailBody = "<html><body><p>You have a new notification.</p></body></html>",
        )

        val actorFallback = if (event.eventType == "comment_resolved") {
            event.resolvedBy.ifEmpty { event.ownerId }
        } else {
            event.ownerId
        }

        val variables = mapOf(
            "actorId" to (event.actorId.ifEmpty { actorFallback }),
            "fileId" to event.fileId,
            "documentId" to event.documentId,
            "commentId" to event.commentId,
            "userId" to event.userId,
        )

        return RenderedNotification(
            title = replaceVariables(template.titleTemplate, variables),
            message = replaceVariables(template.messageTemplate, variables),
            emailSubject = replaceVariables(template.emailSubjectTemplate, variables),
            emailBody = replaceVariables(template.emailBodyTemplate, variables),
        )
    }

    private fun replaceVariables(template: String, variables: Map<String, String>): String {
        var result = template
        for ((key, value) in variables) {
            result = result.replace("{{$key}}", value)
        }
        return result
    }
}
