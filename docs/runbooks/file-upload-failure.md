# Runbook: File Upload Failures

**Severity:** High

## Alert

`FileUploadHighErrorRate` -- fires when file-service 5xx rate exceeds 10% over a 1-minute window.

## Symptoms

- Users cannot upload files; the UI shows generic upload error messages.
- The Chaos Scenarios dashboard shows elevated error rates on the file-service panel.
- Application logs contain `NoSuchBucket` errors from the AWS S3 SDK.

## Investigation Steps

1. Confirm the error in file-service logs:
   ```
   kubectl logs -l app=file-service --tail=100 -n otterworks | grep -i "NoSuchBucket\|S3\|500"
   ```
2. Check the bucket file-service is actually writing to, and that it exists:
   ```
   # config reaches the pod via envFrom, so read it from the running container
   bucket=$(kubectl -n otterworks exec deploy/file-service -- printenv S3_BUCKET)
   echo "file-service writes to: ${bucket}"
   aws s3api head-bucket --bucket "${bucket}"
   ```

<!-- TODO: Complete investigation steps -->

## Resolution Steps

<!-- TODO -->

## Post-Incident

<!-- TODO -->
