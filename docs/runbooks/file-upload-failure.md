# Runbook: File Upload Failures

**Severity:** High

## Alert

`FileUploadHighErrorRate` -- fires when file-service 5xx rate exceeds 10% over a 1-minute window.

## Symptoms

- Users cannot upload files; the UI shows generic upload error messages.
- The file-service panel shows an elevated 5xx rate.
- Application logs contain S3 SDK errors on `PutObject` (e.g. `NoSuchBucket`, `AccessDenied`).

## Investigation Steps

1. Confirm the error in file-service logs:
   ```
   kubectl logs -l app=file-service --tail=100 -n otterworks | grep -i "NoSuchBucket\|S3\|500"
   ```
2. Confirm which bucket the service is writing to and that it exists:
   ```
   kubectl get cm file-service-config -n otterworks -o jsonpath='{.data.S3_BUCKET}'
   aws s3api head-bucket --bucket "$S3_BUCKET"
   ```
3. Check the service account's IAM role still grants `s3:PutObject` on that bucket.

## Resolution Steps

- Wrong or missing bucket name: correct `S3_BUCKET` in the service config and restart the
  deployment.
- Missing permissions: reattach the S3 policy to the file-service IRSA role.

## Post-Incident

<!-- TODO -->
