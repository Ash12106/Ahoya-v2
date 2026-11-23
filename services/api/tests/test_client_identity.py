from ipaddress import ip_address

from app.krawl.client_identity import hash_client_ip, resolve_client_ip


def test_direct_peer_is_used_in_development() -> None:
    assert resolve_client_ip("198.51.100.4", "203.0.113.9", (), production=False) == ip_address(
        "198.51.100.4"
    )


def test_cloudflare_header_is_used_only_from_a_trusted_peer() -> None:
    assert resolve_client_ip(
        "192.0.2.8",
        "203.0.113.9",
        ("192.0.2.0/24",),
        production=True,
    ) == ip_address("203.0.113.9")


def test_forged_cloudflare_header_is_ignored() -> None:
    assert (
        resolve_client_ip(
            "198.51.100.4",
            "203.0.113.9",
            ("192.0.2.0/24",),
            production=True,
        )
        is None
    )


def test_production_without_a_trusted_proxy_does_not_guess_client_ip() -> None:
    assert resolve_client_ip("198.51.100.4", "203.0.113.9", (), production=True) is None


def test_invalid_peer_and_forwarded_addresses_are_rejected() -> None:
    assert (
        resolve_client_ip("not-an-ip", "also-not-an-ip", ("192.0.2.0/24",), production=True) is None
    )


def test_ip_hash_is_stable_keyed_and_does_not_expose_the_address() -> None:
    address = ip_address("203.0.113.9")

    first = hash_client_ip(address, b"a" * 32)
    second = hash_client_ip(address, b"a" * 32)
    other_key = hash_client_ip(address, b"b" * 32)

    assert first == second
    assert first != other_key
    assert str(address) not in first
