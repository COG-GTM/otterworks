using Amazon.S3;
using Amazon.S3.Model;

namespace OtterWorks.AuditService.Services;

// Uploads content written to Buffer in bounded chunks: small objects use a single PutObject,
// larger ones switch to a multipart upload so memory stays near PartSize regardless of object size.
public sealed class S3StreamingUpload : IAsyncDisposable
{
    public const int PartSize = 5 * 1024 * 1024;

    private readonly IAmazonS3 _s3Client;
    private readonly string _bucket;
    private readonly string _key;
    private readonly string _contentType;
    private readonly S3StorageClass? _storageClass;
    private readonly List<PartETag> _parts = new();
    private string? _uploadId;
    private bool _completed;

    public S3StreamingUpload(IAmazonS3 s3Client, string bucket, string key, string contentType, S3StorageClass? storageClass = null)
    {
        _s3Client = s3Client;
        _bucket = bucket;
        _key = key;
        _contentType = contentType;
        _storageClass = storageClass;
    }

    public MemoryStream Buffer { get; } = new();

    public async Task FlushIfFullAsync(CancellationToken cancellationToken = default)
    {
        if (Buffer.Length >= PartSize)
            await UploadPartAsync(cancellationToken);
    }

    public async Task CompleteAsync(CancellationToken cancellationToken = default)
    {
        if (_uploadId is null)
        {
            var putRequest = new PutObjectRequest
            {
                BucketName = _bucket,
                Key = _key,
                InputStream = ReadBuffer(),
                ContentType = _contentType,
            };
            if (_storageClass is not null)
                putRequest.StorageClass = _storageClass;

            await _s3Client.PutObjectAsync(putRequest, cancellationToken);
        }
        else
        {
            if (Buffer.Length > 0)
                await UploadPartAsync(cancellationToken);

            await _s3Client.CompleteMultipartUploadAsync(new CompleteMultipartUploadRequest
            {
                BucketName = _bucket,
                Key = _key,
                UploadId = _uploadId,
                PartETags = _parts,
            }, cancellationToken);
        }

        _completed = true;
    }

    public async ValueTask DisposeAsync()
    {
        if (!_completed && _uploadId is not null)
        {
            try
            {
                await _s3Client.AbortMultipartUploadAsync(new AbortMultipartUploadRequest
                {
                    BucketName = _bucket,
                    Key = _key,
                    UploadId = _uploadId,
                });
            }
            catch (AmazonS3Exception)
            {
                // Incomplete uploads are also cleaned up by bucket lifecycle rules.
            }
        }

        await Buffer.DisposeAsync();
    }

    private async Task UploadPartAsync(CancellationToken cancellationToken)
    {
        if (_uploadId is null)
        {
            var initRequest = new InitiateMultipartUploadRequest
            {
                BucketName = _bucket,
                Key = _key,
                ContentType = _contentType,
            };
            if (_storageClass is not null)
                initRequest.StorageClass = _storageClass;

            var init = await _s3Client.InitiateMultipartUploadAsync(initRequest, cancellationToken);
            _uploadId = init.UploadId;
        }

        var partNumber = _parts.Count + 1;
        var response = await _s3Client.UploadPartAsync(new UploadPartRequest
        {
            BucketName = _bucket,
            Key = _key,
            UploadId = _uploadId,
            PartNumber = partNumber,
            PartSize = Buffer.Length,
            InputStream = ReadBuffer(),
        }, cancellationToken);

        _parts.Add(new PartETag(partNumber, response.ETag));
        Buffer.SetLength(0);
    }

    private MemoryStream ReadBuffer() =>
        new(Buffer.GetBuffer(), 0, (int)Buffer.Length, writable: false);
}
