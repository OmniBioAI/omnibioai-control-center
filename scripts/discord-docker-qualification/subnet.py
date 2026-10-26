"""Pure IPv4 subnet selection and revalidation helpers."""
from __future__ import annotations

import ipaddress
from collections.abc import Iterable


def select_free_subnet(used: Iterable[str], pool: str = "10.240.0.0/12") -> tuple[str, str]:
    networks = [ipaddress.ip_network(value, strict=False) for value in used]
    candidates = ipaddress.ip_network(pool, strict=False).subnets(new_prefix=24)
    for candidate in candidates:
        if not any(candidate.overlaps(existing) for existing in networks):
            return str(candidate), str(candidate.network_address + 1)
    raise RuntimeError(f"no non-overlapping IPv4 /24 remains in {pool}")


def assert_subnet_free(subnet: str, used: Iterable[str]) -> None:
    requested = ipaddress.ip_network(subnet, strict=False)
    conflicts = [str(ipaddress.ip_network(value, strict=False)) for value in used
                 if requested.overlaps(ipaddress.ip_network(value, strict=False))]
    if conflicts:
        raise RuntimeError(f"selected qualification subnet is no longer free: {', '.join(conflicts)}")
