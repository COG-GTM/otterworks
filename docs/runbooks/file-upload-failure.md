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
2. Confirm the bucket file-service is actually writing to. Uploads always target
   `S3_BUCKET`; a `NoSuchBucket` error means that value is wrong for the environment:
   ```
   kubectl get deploy/file-service -n otterworks -o jsonpath='{.spec.template.spec.containers[0].envFrom}'
   S3_BUCKET=$(kubectl exec deploy/file-service -n otterworks -- printenv S3_BUCKET)
   aws s3api head-bucket --bucket "$S3_BUCKET"
   ```

<!-- TODO: Complete investigation steps -->

## Resolution Steps

<!-- TODO -->

## Post-Incident

<!-- TODO -->
