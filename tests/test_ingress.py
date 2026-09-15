"""Helm render contract tests. Run: python3 tests/test_ingress.py"""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


CHART = Path(__file__).resolve().parents[1]
INGRESS = {"enabled": True, "hostPrefix": "aviso.dev", "domain": "example.com"}


def helm(*args, values=None):
    return subprocess.run(
        ["helm", *map(str, args)],
        input=json.dumps(values or {}), capture_output=True, text=True,
    )


class IngressTest(unittest.TestCase):
    def render(self, values=None, chart=CHART, extra=()):
        result = helm("template", "test-release", chart, "--namespace", "test-ns",
                      "--kube-version", "1.29", "-f", "-", *extra, values=values)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [doc for doc in yaml.safe_load_all(result.stdout) if doc]

    def resource(self, docs, kind):
        return next(doc for doc in docs if doc["kind"] == kind)

    def base_url(self, docs):
        config = self.resource(docs, "ConfigMap")["data"]["config.yaml"]
        return yaml.safe_load(config)["application"]["base_url"]

    def test_defaults_and_overrides(self):
        for enabled in (False, True):
            for override in (None, "", "http://custom.example:8000/path", "{{ literal }}"):
                with self.subTest(enabled=enabled, override=override):
                    values = {"ingress": dict(INGRESS, enabled=enabled)}
                    if override is not None:
                        values["config"] = {"application": {"base_url": override}}
                    docs = self.render(values)
                    expected = "http://aviso.dev.example.com" if enabled else "http://aviso-server"
                    self.assertEqual(self.base_url(docs), override or expected)
                    self.assertEqual(sum(d["kind"] == "Ingress" for d in docs), int(enabled))
        self.assertEqual(self.base_url(self.render()), "http://aviso-server")
        docs = self.render({"ingress": dict(INGRESS, tls={"enabled": True, "secretName": "test-tls"}),
                            "config": {"application": {"base_url": "http://explicit.example"}}})
        self.assertEqual(self.base_url(docs), "http://explicit.example")
        self.assertEqual(self.resource(docs, "Ingress")["spec"]["tls"][0]["hosts"],
                         ["aviso.dev.example.com"])

    def test_tls_paths_names_and_annotations(self):
        for tls in (False, True):
            for controller, key, buffering, timeout in (
                ("nginx-org", "nginx.org/", "false", "3600s"),
                ("ingress-nginx", "nginx.ingress.kubernetes.io/", "off", "3600"),
            ):
                with self.subTest(tls=tls, controller=controller):
                    paths = [{"path": "/", "pathType": "Prefix"},
                             {"path": "/api", "pathType": "Exact"},
                             {"path": "/watch", "pathType": "ImplementationSpecific"}]
                    values = {"ingress": dict(
                        INGRESS, className="nginx", paths=paths,
                        tls={"enabled": tls, "secretName": "test-tls"},
                        streamingTuning={"controller": controller},
                        annotations={key + "proxy-read-timeout": "7200",
                                     "example.com/header": "keep"}), "service": {"port": 8123}}
                    docs = self.render(values)
                    ingress = self.resource(docs, "Ingress")
                    service = self.resource(docs, "Service")
                    self.assertEqual(ingress["metadata"]["name"], service["metadata"]["name"])
                    annotations = ingress["metadata"]["annotations"]
                    self.assertEqual(annotations[key + "proxy-buffering"], buffering)
                    self.assertEqual(annotations[key + "proxy-send-timeout"], timeout)
                    self.assertEqual(annotations[key + "proxy-read-timeout"], "7200")
                    self.assertEqual(annotations["example.com/header"], "keep")
                    self.assertEqual(annotations["kubernetes.io/ingress.class"], "nginx")
                    spec = ingress["spec"]
                    self.assertEqual(spec["ingressClassName"], "nginx")
                    self.assertEqual(len(spec["rules"]), 1)
                    self.assertEqual(spec["rules"][0]["host"], "aviso.dev.example.com")
                    for actual, expected in zip(spec["rules"][0]["http"]["paths"], paths):
                        self.assertEqual({k: actual[k] for k in expected}, expected)
                        self.assertEqual(actual["backend"]["service"],
                                         {"name": service["metadata"]["name"], "port": {"number": 8123}})
                    if tls:
                        self.assertEqual(spec["tls"], [{"hosts": ["aviso.dev.example.com"],
                                                        "secretName": "test-tls"}])
                    else:
                        self.assertNotIn("tls", spec)
                    self.assertEqual(self.base_url(docs),
                                     ("https" if tls else "http") + "://aviso.dev.example.com")
        for tuning in ({"enabled": False}, {"controller": ""}):
            docs = self.render({"ingress": dict(INGRESS, streamingTuning=tuning,
                                                annotations={"custom": "kept"})})
            self.assertEqual(self.resource(docs, "Ingress")["metadata"]["annotations"],
                             {"custom": "kept"})

    def test_dns_boundaries(self):
        for host_prefix, domain in (("a", "b"), ("a-1.dev", "region.example.com"),
                               ("a" * 63, ".".join(["b" * 63, "c" * 63, "d" * 61]))):
            with self.subTest(hostPrefix=host_prefix, domain=domain):
                docs = self.render({"ingress": dict(INGRESS, hostPrefix=host_prefix, domain=domain)})
                self.assertEqual(self.base_url(docs), f"http://{host_prefix}.{domain}")

    def test_invalid_contract(self):
        cases = [({"enabled": "false"}, "ingress.enabled"),
                 ({"hosts": []}, "ingress.hosts"),
                 ({"tls": []}, "ingress.tls must be a map"),
                 ({"tls": "bad"}, "ingress.tls must be a map"),
                 ({"tls": {"enabled": "true"}}, "ingress.tls.enabled"),
                 ({"tls": {"enabled": True}}, "ingress.tls.secretName is required"),
                 ({"tls": {"enabled": True, "secretName": "  "}}, "ingress.tls.secretName"),
                 ({"tls": {"secretName": 123}}, "ingress.tls.secretName"),
                 ({"paths": []}, "ingress.paths"), ({"paths": {}}, "ingress.paths"),
                 ({"paths": ["/"]}, "ingress.paths"),
                 ({"paths": [{"path": 1}]}, "absolute path"),
                 ({"paths": [{"path": ""}]}, "absolute path"),
                 ({"paths": [{"path": "api"}]}, "absolute path"),
                 ({"paths": [{"path": "/", "pathType": "Invalid"}]}, "pathType"),
                 ({"paths": [{"path": "/"}]}, "pathType"),
                 ({"hostPrefix": "a" * 63, "domain": ".".join(["b" * 63] * 3)},
                  "composed ingress hostname")]
        for field in ("hostPrefix", "domain"):
            for value in ("", "A", "é", "-a", "a-", "a..b", ".a", "a.",
                          "a_b", "*.example", "http://example", "example:80", "a/b",
                          "a b", "a" * 64, 12, [], {}):
                cases.append(({field: value}, f"ingress.{field}"))
        for patch, message in cases:
            with self.subTest(patch=patch):
                result = helm("template", "test", CHART, "-f", "-", values={
                    "ingress": dict(INGRESS, **patch),
                    "config": {"application": {"base_url": "https://override.example"}}})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
        for ingress in ([], "bad", None):
            result = helm("template", "test", CHART, "-f", "-", values={"ingress": ingress})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ingress must be a map", result.stderr)
        for old in ({"hosts": []}, {"tls": []}):
            result = helm("template", "test", CHART, "-f", "-", values={"ingress": old})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no longer supported", result.stderr)

    def test_public_examples(self):
        examples = sorted((CHART / "examples").glob("values-*.yaml"))
        self.assertEqual(len(examples), 6)
        for example in examples:
            with self.subTest(example=example.name):
                self.render(extra=("-f", example))
                self.render({"ingress": INGRESS}, extra=("-f", example))

    def test_package_and_no_values_mutation(self):
        # Stage only chart inputs; never package checkout metadata/private overlays.
        with tempfile.TemporaryDirectory(prefix="aviso-chart-") as temporary:
            stage = Path(temporary) / "chart"
            stage.mkdir()
            for name in ("Chart.yaml", "Chart.lock", "values.yaml", "README.md"):
                shutil.copy2(CHART / name, stage / name)
            for name in ("templates", "charts", "examples", "dashboards"):
                shutil.copytree(CHART / name, stage / name)
            probe = stage / "templates" / "values-probe.yaml"
            probe.write_text('''{{- $_ := include "aviso-server.validateIngress" . -}}
{{- $_ := include (print $.Template.BasePath "/configmap.yaml") . -}}
apiVersion: v1
kind: ConfigMap
metadata:
  name: values-probe
data:
  original: {{ .Values.config.application.base_url | quote }}
''')
            docs = self.render({"ingress": INGRESS}, chart=stage)
            self.assertEqual(next(d for d in docs if d["metadata"]["name"] == "values-probe")
                             ["data"]["original"], "")
            probe.unlink()
            result = helm("package", stage, "--destination", temporary)
            self.assertEqual(result.returncode, 0, result.stderr)
            package = next(Path(temporary).glob("*.tgz"))
            result = helm("lint", package)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            values = {"ingress": dict(INGRESS, tls={"enabled": True, "secretName": "test-tls"})}
            self.assertEqual(self.render(values, chart=package), self.render(values))


if __name__ == "__main__":
    unittest.main(verbosity=2)
