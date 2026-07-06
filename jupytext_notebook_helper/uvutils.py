import logging
import re
from dataclasses import dataclass
from functools import cache

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib


@dataclass
class UVInformation:
    packages: dict[str, str]
    """Packages associated with their versions (or None if not specified)"""

    build_packages: dict[str, str]
    """Packages necessary for building associated with their versions (or None
    if not specified)"""

    all_packages: dict[str, str]
    """All packages in the lock file (including transitive dependencies)"""

    dependencies: dict[str, set[str]]
    """Mapping from package name to its direct dependencies"""


@cache
def get_uv_versions(uv_lock_path="uv.lock", project_path="pyproject.toml"):
    """
    Returns a list of top-level pinned dependencies from uv.lock
    as pip-compatible requirement strings.
    """

    with open(uv_lock_path, "rb") as f:
        uvlock = tomllib.load(f)

    all_packages_list = uvlock.get("package", [])

    locked: dict[str, str] = {}
    for p in all_packages_list:
        if version := p.get("version"):
            locked[p["name"].lower()] = version
        else:
            logging.info("Package %s version missing from lock", p["name"])

    # Build dependency graph from lock file
    dependencies = {}
    for pkg in all_packages_list:
        pkg_name = pkg["name"].lower()
        pkg_deps = set()
        for dep in pkg.get("dependencies", []):
            # Dependencies can be dicts with "name" key or just strings
            if isinstance(dep, dict):
                pkg_deps.add(dep["name"].lower())
            else:
                # Parse dependency string (e.g., "requests>=2.0" -> "requests")
                dep_name = re.match(r"^([a-zA-Z0-9_-]+)", dep)
                if dep_name:
                    pkg_deps.add(dep_name.group(1).lower())
        dependencies[pkg_name] = pkg_deps

    # Get packages
    packages = {}
    requires_dist = (
        next(p for p in uvlock.get("package", []) if "metadata" in p)
        .get("metadata")
        .get("requires-dist")
    )
    for dep in requires_dist:
        name = dep["name"]
        extras = dep.get("extras", [])
        extras_str = f"[{','.join(extras)}]" if extras else ""
        pinned_version = locked.get(name.lower())

        package_name = f"{name}{extras_str}"

        if pinned_version:
            packages[package_name] = pinned_version
        else:
            packages[package_name] = None
            logging.info("Package %s version missing from lock", package_name)

    # Build requirements
    with open(project_path, "rb") as f:
        project = tomllib.load(f)
        build_requires = project.get("build-system", {}).get("requires", [])
        build_packages = {}
        for name in build_requires:
            # Extract package name from version specifier (e.g.,
            # "setuptools>=40.8.0" -> "setuptools")
            match = re.match(r"^([a-zA-Z0-9_-]+)", name)
            package_name = match.group(1) if match else name
            pinned_version = locked.get(package_name.lower())
            if pinned_version:
                build_packages[package_name] = pinned_version
            else:
                build_packages[package_name] = None
                logging.info("Package %s version missing from lock", name)

    return UVInformation(packages, build_packages, locked, dependencies)


# example usage
if __name__ == "__main__":
    info = get_uv_versions()
    for p in info.build_packages.items():
        print(" -- ", p)
    for p in info.packages.items():
        print(p)
