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
   # deploy-tenant.sh always sets S3_BUCKET (the shared dev bucket, e.g.
   # otterworks-files-dev), so an unset value means the tenant was deployed
   # without that wiring and the service falls back to its built-in default
   echo "file-service writes to: ${bucket:-otterworks-files (code default)}"
   aws s3api head-bucket --bucket "${bucket:-otterworks-files}"
   ```
   If the variable is unset, treat that as the finding: re-run
   `scripts/deploy-tenant.sh <ID>` so the release carries `config.S3_BUCKET`.

<!-- TODO: Complete investigation steps -->

## Resolution Steps

<!-- TODO -->

## Post-Incident

<!-- TODO -->
