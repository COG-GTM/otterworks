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
2. Check the bucket file-service is actually configured with, and that it exists:
   ```
   S3_BUCKET=$(kubectl get deploy/file-service -n otterworks \
     -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="S3_BUCKET")].value}')
   # Tenant deploys usually set it via envFrom, so fall back to the ConfigMap.
   : "${S3_BUCKET:=$(kubectl get cm -n otterworks -l app=file-service \
     -o jsonpath='{.items[*].data.S3_BUCKET}')}"
   echo "configured bucket: ${S3_BUCKET:-<not found>}"
   [ -n "$S3_BUCKET" ] && aws s3api head-bucket --bucket "$S3_BUCKET"
   ```

<!-- TODO: Complete investigation steps -->

## Resolution Steps

<!-- TODO -->

## Post-Incident

<!-- TODO -->
