{{/*
Expand the chart name.
*/}}
{{- define "multi-agent.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully-qualified app name.
*/}}
{{- define "multi-agent.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart label: name-version
*/}}
{{- define "multi-agent.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels attached to every resource.
*/}}
{{- define "multi-agent.labels" -}}
helm.sh/chart: {{ include "multi-agent.chart" . }}
{{ include "multi-agent.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels — used in matchLabels and pod template labels.
*/}}
{{- define "multi-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ include "multi-agent.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Name of the Secret that holds application secrets.
Supports using a pre-existing secret via secrets.existingSecret.
*/}}
{{- define "multi-agent.secretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- include "multi-agent.fullname" . }}-secrets
{{- end }}
{{- end }}

{{/*
Name of the ConfigMap with non-secret configuration.
*/}}
{{- define "multi-agent.configMapName" -}}
{{- include "multi-agent.fullname" . }}-config
{{- end }}

{{/*
Internal service name for PostgreSQL.
*/}}
{{- define "multi-agent.postgresServiceName" -}}
{{- include "multi-agent.fullname" . }}-postgres
{{- end }}

{{/*
Internal service name for the mock carrier API.
*/}}
{{- define "multi-agent.mockApiServiceName" -}}
{{- include "multi-agent.fullname" . }}-mock-api
{{- end }}

{{/*
Internal service name for Prometheus.
*/}}
{{- define "multi-agent.prometheusServiceName" -}}
{{- include "multi-agent.fullname" . }}-prometheus
{{- end }}
