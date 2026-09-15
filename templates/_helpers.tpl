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

{{/* Validate the ingress contract even when disabled or base_url is overridden. */}}
{{- define "aviso-server.validateIngress" -}}
{{- $i := .Values.ingress -}}
{{- if not (kindIs "map" $i) -}}{{ fail "ingress must be a map" }}{{- end -}}
{{- if hasKey $i "hosts" -}}{{ fail "ingress.hosts is no longer supported; use ingress.hostPrefix, ingress.domain and ingress.paths" }}{{- end -}}
{{- if not (kindIs "bool" $i.enabled) -}}{{ fail "ingress.enabled must be a boolean" }}{{- end -}}
{{- if not (kindIs "map" $i.tls) -}}{{ fail "ingress.tls must be a map with enabled and secretName; TLS lists are no longer supported" }}{{- end -}}
{{- if not (kindIs "bool" $i.tls.enabled) -}}{{ fail "ingress.tls.enabled must be a boolean" }}{{- end -}}
{{- if not (kindIs "string" $i.tls.secretName) -}}{{ fail "ingress.tls.secretName must be a string" }}{{- end -}}
{{- if and $i.tls.enabled (empty (trim $i.tls.secretName)) -}}{{ fail "ingress.tls.secretName is required when ingress.tls.enabled is true" }}{{- end -}}
{{- if $i.tls.enabled -}}
  {{/* Kubernetes Secret names allow 253 bytes total without a per-label limit: test.tls is valid; TEST_TLS is not. */}}
  {{- if or (gt (len $i.tls.secretName) 253) (not (regexMatch "^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$" $i.tls.secretName)) -}}
    {{- fail "ingress.tls.secretName must be a lowercase RFC 1123 subdomain of at most 253 characters" -}}
  {{- end -}}
{{- end -}}
{{- range $key := list "hostPrefix" "domain" -}}
  {{- $value := index $i $key -}}
  {{- if not (kindIs "string" $value) -}}{{ fail (printf "ingress.%s must be a string" $key) }}{{- end -}}
  {{- if or $i.enabled (ne $value "") -}}
    {{- include "aviso-server.validateDNS" (dict "name" (printf "ingress.%s" $key) "value" $value) -}}
  {{- end -}}
{{- end -}}
{{- if $i.enabled -}}
  {{- include "aviso-server.validateDNS" (dict "name" "composed ingress hostname" "value" (include "aviso-server.ingressHost" .)) -}}
{{- end -}}
{{- if not (kindIs "slice" $i.paths) -}}{{ fail "ingress.paths must be a nonempty list" }}{{- end -}}
{{- if empty $i.paths -}}{{ fail "ingress.paths must be a nonempty list" }}{{- end -}}
{{- range $i.paths -}}
  {{- if not (kindIs "map" .) -}}{{ fail "ingress.paths entries must be maps with path and pathType" }}{{- end -}}
  {{- if not (kindIs "string" .path) -}}{{ fail "ingress.paths path must be an absolute path string" }}{{- end -}}
  {{- if not (hasPrefix "/" .path) -}}{{ fail "ingress.paths path must be a nonempty absolute path starting with /" }}{{- end -}}
  {{- if not (has .pathType (list "Prefix" "Exact" "ImplementationSpecific")) -}}{{ fail "ingress.paths pathType must be Prefix, Exact or ImplementationSpecific" }}{{- end -}}
  {{- if has .pathType (list "Prefix" "Exact") -}}
    {{/* Match Kubernetes path validation: /api/watch is valid; /api//watch is not. */}}
    {{- $path := .path -}}
    {{- range list "//" "/./" "/../" "%2f" "%2F" -}}
      {{- if contains . $path -}}{{ fail (printf "ingress.paths path must not contain %s for Prefix or Exact" .) }}{{- end -}}
    {{- end -}}
    {{- range list "/.." "/." -}}
      {{- if hasSuffix . $path -}}{{ fail (printf "ingress.paths path must not end with %s for Prefix or Exact" .) }}{{- end -}}
    {{- end -}}
  {{- end -}}
{{- end -}}
{{- end -}}

{{/* DNS subdomains: ASCII lowercase labels, 63 bytes each, 253 total. */}}
{{- define "aviso-server.validateDNS" -}}
{{- if or (empty .value) (gt (len .value) 253) -}}{{ fail (printf "%s is required and must be a DNS name of at most 253 characters" .name) }}{{- end -}}
{{- range splitList "." .value -}}
  {{- if or (gt (len .) 63) (not (regexMatch "^[a-z0-9]([a-z0-9-]*[a-z0-9])?$" .)) -}}
    {{- fail (printf "%s must contain lowercase ASCII DNS labels (1-63 characters, letters/digits at each end); no scheme, port or path" $.name) -}}
  {{- end -}}
{{- end -}}
{{- end -}}

{{- define "aviso-server.ingressHost" -}}
{{- printf "%s.%s" .Values.ingress.hostPrefix .Values.ingress.domain -}}
{{- end -}}

{{- define "aviso-server.applicationBaseURL" -}}
{{- if .Values.config.application.base_url -}}
{{- .Values.config.application.base_url -}}
{{- else if .Values.ingress.enabled -}}
{{- printf "%s://%s" (ternary "https" "http" .Values.ingress.tls.enabled) (include "aviso-server.ingressHost" .) -}}
{{- else -}}
http://aviso-server
{{- end -}}
{{- end -}}

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
