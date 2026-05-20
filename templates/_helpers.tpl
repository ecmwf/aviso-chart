{{/*
Expand the name of the chart.
*/}}
{{- define "aviso-server.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "aviso-server.fullname" -}}
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
Create chart name and version as used by the chart label.
*/}}
{{- define "aviso-server.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "aviso-server.labels" -}}
helm.sh/chart: {{ include "aviso-server.chart" . }}
{{ include "aviso-server.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "aviso-server.selectorLabels" -}}
app.kubernetes.io/name: {{ include "aviso-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the image pull secret
*/}}
{{- define "aviso-server.imagePullSecretName" -}}
{{- printf "%s-registry-secret" (include "aviso-server.fullname" .) }}
{{- end }}

{{/*
Ingress annotations for aviso's long-lived SSE connections.

Returns the merged annotation map for the configured ingress controller,
honoring .Values.ingress.streamingTuning.{enabled,controller,proxyBuffering,
proxyReadTimeoutSeconds,proxySendTimeoutSeconds}. Operator-supplied
.Values.ingress.annotations entries always win on key collision so a
single annotation can be overridden without disabling the whole block.

Supported controllers:
  - "nginx-org"      F5 NGINX Ingress Controller (nginx.org/*)
  - "ingress-nginx"  Kubernetes ingress-nginx     (nginx.ingress.kubernetes.io/*)
  - ""               No auto-emit; fall back to ingress.annotations only.
*/}}
{{- define "aviso-server.ingressAnnotations" -}}
{{- $tuning := .Values.ingress.streamingTuning | default dict -}}
{{- $auto := dict -}}
{{- if and (hasKey $tuning "enabled") $tuning.enabled -}}
  {{- $controller := $tuning.controller | default "" -}}
  {{- $bufferingOff := not $tuning.proxyBuffering -}}
  {{- $readTimeout := printf "%vs" (int $tuning.proxyReadTimeoutSeconds) -}}
  {{- $sendTimeout := printf "%vs" (int $tuning.proxySendTimeoutSeconds) -}}
  {{- if eq $controller "nginx-org" -}}
    {{- $_ := set $auto "nginx.org/proxy-buffering" (ternary "false" "true" $bufferingOff) -}}
    {{- $_ := set $auto "nginx.org/proxy-read-timeout" $readTimeout -}}
    {{- $_ := set $auto "nginx.org/proxy-send-timeout" $sendTimeout -}}
  {{- else if eq $controller "ingress-nginx" -}}
    {{- $_ := set $auto "nginx.ingress.kubernetes.io/proxy-buffering" (ternary "off" "on" $bufferingOff) -}}
    {{- $_ := set $auto "nginx.ingress.kubernetes.io/proxy-read-timeout" (printf "%v" (int $tuning.proxyReadTimeoutSeconds)) -}}
    {{- $_ := set $auto "nginx.ingress.kubernetes.io/proxy-send-timeout" (printf "%v" (int $tuning.proxySendTimeoutSeconds)) -}}
  {{- end -}}
{{- end -}}
{{- $user := .Values.ingress.annotations | default dict -}}
{{- $merged := merge (deepCopy $user) $auto -}}
{{- if and .Values.ingress.className (not (hasKey $merged "kubernetes.io/ingress.class")) -}}
  {{- $_ := set $merged "kubernetes.io/ingress.class" .Values.ingress.className -}}
{{- end -}}
{{- toYaml $merged -}}
{{- end }}
