# /// script
# requires-python = ">=3.11"
# ///
"""Derive the edge-reachable route inventory from OtterWorks source.

A black-box scanner only finds what it can crawl, so an endpoint nothing links
to is an endpoint nothing tests. Reading the code instead gives the *intended*
surface — including routes added yesterday — which is what the DAST suite's
coverage is measured against.

The gateway's own route table is the authority on what is reachable at the edge:
a backend route whose prefix the gateway does not proxy is not attackable from
outside, and one it does proxy is, whatever the frontend happens to link to.

Extraction is per-language and deliberately literal: a route is reported only
when its path is a string in the source. Anything assembled at runtime is not
reported, and a service with no extractor is reported as *unknown* rather than
as covered — an unverifiable claim about coverage is the failure mode this whole
module exists to prevent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICES = REPO_ROOT / "services"
GATEWAY_CONFIG = SERVICES / "api-gateway" / "internal" / "config" / "config.go"

#: `"/api/v1/auth": c.AuthServiceURL,` inside ServiceRoutes().
_GATEWAY_ROUTE = re.compile(r'"(?P<prefix>/[^"]+)":\s*c\.(?P<field>\w+)ServiceURL')
_METHODS = ("get", "post", "put", "patch", "delete")


@dataclass(frozen=True)
class Route:
    """One edge-reachable endpoint, as declared in a service's source."""

    method: str
    path: str
    service: str
    source: str

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


def _camel_to_kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def gateway_prefixes(config: Path = GATEWAY_CONFIG) -> dict[str, str]:
    """Proxied prefix -> service directory name, from the gateway's route table."""
    if not config.exists():
        return {}
    return {
        match["prefix"]: f"{_camel_to_kebab(match['field'])}-service"
        for match in _GATEWAY_ROUTE.finditer(config.read_text())
    }


def repo_relative(path: Path) -> str:
    """Where a route was declared, repo-relative when the file is in the repo."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _join(*parts: str) -> str:
    joined = "/".join(part.strip("/") for part in parts if part.strip("/"))
    return f"/{joined}" if joined else "/"


def _normalize(path: str) -> str:
    """Rewrite every path-parameter syntax to `{}` so paths compare across languages."""
    path = re.sub(r"\{[^}/]*\}", "{}", path)  # FastAPI, actix, Spring
    path = re.sub(r"<[^>/]*>", "{}", path)  # Flask
    path = re.sub(r":[^/]+", "{}", path)  # Rails, Express
    return path.rstrip("/") or "/"


# ── per-language extractors ───────────────────────────────────────────────────


def _fastapi(service: Path, name: str) -> list[Route]:
    """FastAPI: `include_router(mod.router, prefix=...)` plus `@router.<method>`."""
    main = service / "app" / "main.py"
    if not main.exists():
        return []
    prefixes: dict[str, list[str]] = {}
    for match in re.finditer(
        r"include_router\(\s*(\w+)\.router(?:\s*,\s*prefix=\"([^\"]*)\")?", main.read_text()
    ):
        prefixes.setdefault(match[1], []).append(match[2] or "")
    routes: list[Route] = []
    for module, mounts in prefixes.items():
        path = service / "app" / "api" / f"{module}.py"
        if not path.exists():
            continue
        text = path.read_text()
        for match in re.finditer(
            rf"@router\.({'|'.join(_METHODS)})\(\s*\"([^\"]*)\"", text, re.IGNORECASE
        ):
            for mount in mounts:
                routes.append(
                    Route(
                        match[1].upper(),
                        _normalize(_join(mount, match[2])),
                        name,
                        repo_relative(path),
                    )
                )
    return routes


def _flask(service: Path, name: str) -> list[Route]:
    """Flask: `register_blueprint(bp, url_prefix=...)` plus `@bp.route`."""
    main = service / "app" / "main.py"
    if not main.exists():
        return []
    prefixes: dict[str, list[str]] = {}
    for match in re.finditer(
        r"register_blueprint\(\s*(\w+)(?:\s*,\s*url_prefix=\"([^\"]*)\")?", main.read_text()
    ):
        prefixes.setdefault(match[1], []).append(match[2] or "")
    routes: list[Route] = []
    for path in sorted((service / "app" / "api").glob("*.py")):
        text = path.read_text()
        for match in re.finditer(
            r"@(\w+)\.route\(\s*\"([^\"]*)\"(?:[^)]*methods=\[([^\]]*)\])?", text
        ):
            methods = (
                [m.strip().strip("\"'").upper() for m in match[3].split(",")]
                if match[3]
                else ["GET"]
            )
            for mount in prefixes.get(match[1], []):
                for method in methods:
                    routes.append(
                        Route(
                            method,
                            _normalize(_join(mount, match[2])),
                            name,
                            repo_relative(path),
                        )
                    )
    return routes


def _actix(service: Path, name: str) -> list[Route]:
    """Actix-web: `web::scope("…")` blocks containing `.route("…", web::<method>()…)`."""
    main = service / "src" / "main.rs"
    if not main.exists():
        return []
    text = main.read_text()
    routes: list[Route] = []
    scopes: list[tuple[int, str]] = [
        (match.end(), match[1]) for match in re.finditer(r'web::scope\("([^"]*)"\)', text)
    ]
    for match in re.finditer(
        rf'\.route\(\s*"([^"]*)"\s*,\s*web::({"|".join(_METHODS)})\(\)', text, re.DOTALL
    ):
        # The nearest scope opened before this route is the one it is mounted in;
        # actix nests scopes textually, so source order is the mounting order.
        mount = next((prefix for start, prefix in reversed(scopes) if start < match.start()), "")
        routes.append(
            Route(
                match[2].upper(),
                _normalize(_join(mount, match[1])),
                name,
                repo_relative(main),
            )
        )
    return routes


_SPRING_CLASS = re.compile(r'@RequestMapping\(\s*"([^"]*)"')
_SPRING_METHOD = re.compile(r'@(Get|Post|Put|Patch|Delete)Mapping(?:\(\s*"([^"]*)")?')


def _spring(service: Path, name: str) -> list[Route]:
    """Spring MVC: class-level `@RequestMapping` plus method-level `@<Verb>Mapping`."""
    routes: list[Route] = []
    for suffix in ("*.java", "*.kt"):
        for path in sorted((service / "src" / "main").rglob(suffix)):
            text = path.read_text()
            class_match = _SPRING_CLASS.search(text)
            mount = class_match[1] if class_match else ""
            for match in _SPRING_METHOD.finditer(text):
                routes.append(
                    Route(
                        match[1].upper(),
                        _normalize(_join(mount, match[2] or "")),
                        name,
                        repo_relative(path),
                    )
                )
    return routes


#: Only services whose routes can be read literally are extracted. The rest are
#: reported as unknown coverage, which is the honest answer: see module docstring.
EXTRACTORS = {
    "auth-service": _spring,
    "document-service": _fastapi,
    "file-service": _actix,
    "search-service": _flask,
    "report-service": _spring,
    "notification-service": _spring,
}


def service_routes(name: str) -> list[Route] | None:
    """Routes declared by a service, or None when it has no extractor."""
    extractor = EXTRACTORS.get(name)
    if extractor is None:
        return None
    service = SERVICES / name
    return extractor(service, name) if service.exists() else []


def edge_routes() -> tuple[list[Route], dict[str, str]]:
    """(routes reachable through the gateway, prefixes whose service has no extractor).

    A backend route only counts when the gateway proxies its prefix: the suite
    attacks the deployed edge, and a route behind no proxied prefix is not part
    of that surface.
    """
    prefixes = gateway_prefixes()
    routes: list[Route] = []
    unknown: dict[str, str] = {}
    by_service: dict[str, list[Route] | None] = {}
    for prefix, service in sorted(prefixes.items()):
        if service not in by_service:
            by_service[service] = service_routes(service)
        declared = by_service[service]
        if declared is None:
            unknown[prefix] = service
            continue
        routes.extend(route for route in declared if route.path.startswith(prefix))
    return sorted(set(routes), key=lambda r: (r.path, r.method)), unknown


if __name__ == "__main__":
    from tabulate import tabulate

    inventory, unmapped = edge_routes()
    print(
        tabulate(
            [[route.method, route.path, route.service, route.source] for route in inventory],
            headers=["method", "path", "service", "declared in"],
        )
    )
    if unmapped:
        print(
            "\nProxied prefixes with no route extractor (coverage unmeasured):\n  "
            + "\n  ".join(f"{prefix} ({service})" for prefix, service in sorted(unmapped.items()))
        )
