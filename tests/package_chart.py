"""Package the checkout and remove repository metadata embedded in dependencies."""

from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from test_package import check_package


def package_chart(source, output, version=None):
    with tempfile.TemporaryDirectory() as temporary:
        command = ["helm", "package", str(source), "-d", temporary]
        if version:
            command.extend(["--version", version])
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("helm package failed")
        package, = Path(temporary).glob("*.tgz")
        check_package(package, final=False)
        destination = Path(output) / package.name
        with tarfile.open(package) as original, tarfile.open(destination, "w:gz") as clean:
            for member in original:
                parts = Path(member.name).parts
                # Root exclusions must work via .helmignore. Only scrub metadata
                # embedded in upstream archives, without altering dependencies.
                if len(parts) > 3 and parts[1] == "charts" and {".git", ".github"}.intersection(parts):
                    continue
                clean.addfile(member, original.extractfile(member) if member.isfile() else None)
        check_package(destination)
        return destination


if __name__ == "__main__":
    package_chart(Path(__file__).resolve().parents[1], Path.cwd(), sys.argv[1])
