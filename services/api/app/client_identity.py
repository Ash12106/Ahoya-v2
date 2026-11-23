"""Client address parsing and privacy-preserving identifiers."""

import hashlib
import hmac
from ipaddress import IPv4Address, IPv6Address, ip_address, ip_network

IPAddress = IPv4Address | IPv6Address


def resolve_client_ip(
    peer_address: str | None,
    forwarded_address: str | None,
    trusted_proxy_cidrs: tuple[str, ...],
    production: bool,
) -> IPAddress | None:
    """Resolve an address only from a direct peer trusted to forward it."""
    try:
        peer = ip_address(peer_address) if peer_address else None
    except ValueError:
        return None

    if peer is None:
        return None

    if not production:
        return peer

    trusted_networks = tuple(ip_network(cidr, strict=False) for cidr in trusted_proxy_cidrs)
    if not any(peer in network for network in trusted_networks):
        return None

    try:
        return ip_address(forwarded_address) if forwarded_address else None
    except ValueError:
        return None


def hash_client_ip(address: IPAddress, secret: bytes) -> str:
    """Return a keyed digest for short-lived ban and event correlation."""
    return hmac.new(secret, address.packed, hashlib.sha256).hexdigest()
