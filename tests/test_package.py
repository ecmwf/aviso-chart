"""Check real-checkout and synthetic packaging without printing file contents."""

from pathlib import Path, PurePosixPath
import shutil
import hashlib
import subprocess
import tarfile
import tempfile
import unittest


CHART = Path(__file__).resolve().parents[1]
FORBIDDEN = {".git", ".github", ".idea", ".vscode", ".env", ".venv",
             "venv", "__pycache__", ".kube", "kubeconfig", "private",
             "tmp", "dist", "build"}


def check_package(package, final=True):
    """Reusable on the downloaded OCI artifact; inspect names before contents."""
    with tarfile.open(package) as archive:
        names = set(archive.getnames())
    for name in names:
        path = PurePosixPath(name)
        assert not name.startswith("aviso-chart/tests/")
        assert not path.is_absolute() and ".." not in path.parts
        # Pinned upstream workflows are stripped by the final packaging step.
        forbidden = FORBIDDEN if final else FORBIDDEN - {".github"}
        assert not forbidden.intersection(path.parts), "Forbidden package metadata"
        assert not name.startswith("aviso-chart/.github/")
        assert not any(p.startswith((".env.", "kubeconfig.")) for p in path.parts)
        assert path.suffix not in {".pyc", ".tmp", ".swp", ".prov"}
        assert not name.endswith("~")
        assert not (len(path.parts) == 2 and path.suffix == ".tgz")
    required = {"Chart.yaml", "Chart.lock", "values.yaml", "README.md"}
    required.update(str(p.relative_to(CHART)) for p in (CHART / "templates").rglob("*")
                    if p.is_file())
    # Helm expands dependency archives into the parent package.
    required.update({"charts/nats/Chart.yaml", "charts/nats/values.yaml",
                     "charts/auth-o-tron-chart/Chart.yaml",
                     "charts/auth-o-tron-chart/values.yaml"})
    assert {"aviso-chart/" + p for p in required} <= names, "Missing chart inputs"
    return len(names)


class PackageTest(unittest.TestCase):
    def package(self, source, output):
        from package_chart import package_chart
        package = package_chart(source, output)
        check_package(package)
        for command in (["helm", "lint", str(package)],
                        ["helm", "template", "test-release", str(package)]):
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, "Packaged chart lint/render failed")

    def test_actual_checkout(self):
        self.assertTrue((CHART / ".git").exists(), "Test requires a real checkout")
        with tempfile.TemporaryDirectory() as temporary:
            self.package(CHART, Path(temporary))

    def test_ignored_development_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            for name in ("Chart.yaml", "Chart.lock", "values.yaml", "README.md", ".helmignore"):
                shutil.copy2(CHART / name, source / name)
            for name in ("templates", "charts"):
                shutil.copytree(CHART / name, source / name)
            for name in (".git/config", ".github/workflows/private.yaml", ".env",
                         ".env.local", "private/values.yaml", "tmp/rendered.yaml",
                         "dist/rendered.yaml", "build/output", ".kube/config",
                         "kubeconfig", "kubeconfig.dev", "old-chart.tgz", "old-chart.prov",
                         "templates/__pycache__/test.pyc", "templates/ignored.tmp",
                         "templates/ignored.swp", "templates/ignored~"):
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("synthetic packaging sentinel\n")
            output = root / "output"
            output.mkdir()
            self.package(source, output)

    def test_dependency_payload_preserved(self):
        from package_chart import package_chart
        def payload(path):
            with tarfile.open(path) as archive:
                return {m.name: hashlib.sha256(archive.extractfile(m).read()).digest()
                        for m in archive if m.isfile()
                        and m.name.startswith("aviso-chart/charts/")
                        and not {".git", ".github"}.intersection(PurePosixPath(m.name).parts)}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            package = package_chart(CHART, output)
            raw = output / "raw"
            raw.mkdir()
            result = subprocess.run(["helm", "package", str(CHART), "-d", str(raw)],
                                    capture_output=True)
            self.assertEqual(result.returncode, 0)
            original, = raw.glob("*.tgz")
            self.assertTrue(payload(original))
            self.assertTrue(payload(original) == payload(package), "Dependency payload changed")


if __name__ == "__main__":
    unittest.main()
