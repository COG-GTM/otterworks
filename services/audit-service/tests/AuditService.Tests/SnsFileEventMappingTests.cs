using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class SnsFileEventMappingTests
{
    [Fact]
    public void ToAuditEvent_ShouldMapRenameWithPreviousName()
    {
        var fileEvent = new SnsConsumer.FileEventMessage
        {
            EventType = "file_updated",
            FileId = "file-1",
            OwnerId = "owner-1",
            ActorId = "actor-1",
            Name = "Q4.xlsx",
            PreviousName = "Q3.xlsx",
        };

        var entity = SnsConsumer.ToAuditEvent("msg-1", fileEvent);

        Assert.Equal("rename", entity.Action);
        Assert.Equal("actor-1", entity.UserId);
        Assert.Equal("file", entity.ResourceType);
        Assert.Equal("file-1", entity.ResourceId);
        Assert.Equal("Q3.xlsx", entity.Details!["previousName"]);
        Assert.Equal("Q4.xlsx", entity.Details["name"]);
    }

    [Fact]
    public void ToAuditEvent_ShouldMapShareWithPermission()
    {
        var fileEvent = new SnsConsumer.FileEventMessage
        {
            EventType = "file_shared",
            FileId = "file-1",
            OwnerId = "owner-1",
            SharedWithUserId = "user-2",
            Permission = "editor",
        };

        var entity = SnsConsumer.ToAuditEvent("msg-2", fileEvent);

        Assert.Equal("share", entity.Action);
        Assert.Equal("owner-1", entity.UserId);
        Assert.Equal("user-2", entity.Details!["sharedWithUserId"]);
        Assert.Equal("editor", entity.Details["permission"]);
    }

    [Fact]
    public void ToAuditEvent_ShouldMapMoveWithFolderName()
    {
        var fileEvent = new SnsConsumer.FileEventMessage
        {
            EventType = "file_moved",
            FileId = "file-1",
            OwnerId = "owner-1",
            ActorId = "owner-1",
            FolderId = "folder-9",
            FolderName = "Finance/2026",
        };

        var entity = SnsConsumer.ToAuditEvent("msg-3", fileEvent);

        Assert.Equal("move", entity.Action);
        Assert.Equal("Finance/2026", entity.Details!["folderName"]);
    }

    [Fact]
    public void ToAuditEvent_ShouldMapDownloadWithoutDetailsNoise()
    {
        var fileEvent = new SnsConsumer.FileEventMessage
        {
            EventType = "file_downloaded",
            FileId = "file-1",
            OwnerId = "owner-1",
            ActorId = "user-2",
            Name = "Q4.xlsx",
        };

        var entity = SnsConsumer.ToAuditEvent("msg-4", fileEvent);

        Assert.Equal("download", entity.Action);
        Assert.Equal("user-2", entity.UserId);
        Assert.Equal(new[] { "name" }, entity.Details!.Keys);
    }
}
