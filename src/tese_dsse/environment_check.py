from __future__ import annotations

import importlib
import importlib.metadata as metadata
import platform
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PackageStatus:
    name: str
    module: str
    installed: bool
    version: str | None
    error: str | None = None


PACKAGES = [
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("pandas", "pandas"),
    ("matplotlib", "matplotlib"),
    ("numba", "numba"),
    ("plotly", "plotly"),
    ("igraph", "igraph"),
    ("pandapower", "pandapower"),
    ("opendssdirect.py", "opendssdirect"),
]


def _package_version(distribution_name: str, module_name: str) -> str | None:
    candidates = [distribution_name, module_name]
    if distribution_name == "opendssdirect.py":
        candidates.extend(["OpenDSSDirect.py", "dss-python"])

    for candidate in candidates:
        try:
            return metadata.version(candidate)
        except metadata.PackageNotFoundError:
            pass
    return None


def collect_package_status() -> list[PackageStatus]:
    status: list[PackageStatus] = []
    for distribution_name, module_name in PACKAGES:
        try:
            importlib.import_module(module_name)
            status.append(
                PackageStatus(
                    name=distribution_name,
                    module=module_name,
                    installed=True,
                    version=_package_version(distribution_name, module_name),
                )
            )
        except Exception as exc:  # pragma: no cover - diagnostic path
            status.append(
                PackageStatus(
                    name=distribution_name,
                    module=module_name,
                    installed=False,
                    version=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return status


def environment_report() -> dict:
    return {
        "python": sys.version.replace("\n", " "),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "packages": [package.__dict__ for package in collect_package_status()],
    }


def print_environment_report() -> None:
    report = environment_report()
    print(f"Python: {report['python']}")
    print(f"Executable: {report['python_executable']}")
    print(f"Platform: {report['platform']}")
    print("")
    for package in collect_package_status():
        marker = "OK" if package.installed else "MISSING"
        version = package.version or "-"
        print(f"{marker:7} {package.name:18} module={package.module:15} version={version}")
        if package.error:
            print(f"        {package.error}")


if __name__ == "__main__":
    print_environment_report()
