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
2. Confirm the bucket file-service is actually writing to -- uploads always target
   `S3_BUCKET`, so a `NoSuchBucket` means that value is wrong for the environment:
   ```
   kubectl -n otterworks get deploy/file-service -o jsonpath='{.spec.template.spec.containers[0].envFrom}'
   kubectl -n otterworks get cm file-service-config -o jsonpath='{.data.S3_BUCKET}'
   ```
3. Verify the bucket exists and the pod's IRSA role can write to it:
   ```
   aws s3api head-bucket --bucket "$S3_BUCKET"
   ```

## Resolution Steps

1. Point `config.S3_BUCKET` at the bucket that exists for the environment and roll
   file-service (`helm upgrade ... && kubectl rollout restart deploy/file-service`).
2. Re-run an upload from the web app and confirm a 201 plus the object in S3.

## Post-Incident

<!-- TODO -->
