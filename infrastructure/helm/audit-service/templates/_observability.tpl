{{/*
OpenTelemetry wiring for the shared in-cluster collector
(demo-platform/k8s/observability). Renders nothing unless
observability.otel.enabled=true, so existing releases are unchanged.
*/}}
{{- define "otterworks.otelEnv" -}}
{{- $otel := (.Values.observability | default dict).otel | default dict -}}
{{- if $otel.enabled }}
- name: OTEL_ENABLED
  value: "true"
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ required "observability.otel.endpoint is required when observability.otel.enabled=true" $otel.endpoint | quote }}
- name: OTEL_EXPORTER_OTLP_PROTOCOL
  value: {{ $otel.protocol | default "http/protobuf" | quote }}
- name: OTEL_SERVICE_NAME
  value: {{ $otel.serviceName | default .Chart.Name | quote }}
- name: OTEL_K8S_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
- name: OTEL_K8S_POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
- name: OTEL_RESOURCE_ATTRIBUTES
  value: "service.namespace=$(OTEL_K8S_NAMESPACE),k8s.namespace.name=$(OTEL_K8S_NAMESPACE),k8s.pod.name=$(OTEL_K8S_POD_NAME),otterworks.tenant=$(OTEL_K8S_NAMESPACE)
  {{- range $k, $v := $otel.resourceAttributes }},{{ $k }}={{ $v }}{{ end }}"
{{- end }}
{{- end }}
