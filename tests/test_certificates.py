# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for reading a node's certificate expiry."""

import dataclasses

from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.coordinator import parse_certificates
from custom_components.proxmoxve.models import ProxmoxCertificateData

# Shaped like `GET /nodes/<node>/certificates/info`, with invented values. The
# real response also carries the whole certificate in a `pem` field, plus
# `fingerprint`, `san` and the key details; one entry is returned per
# certificate file that exists on the node.
ROOT_CA = {
    "filename": "pve-root-ca.pem",
    "issuer": "/CN=Example/O=Example Cluster Manager CA",
    "subject": "/CN=Example/O=Example Cluster Manager CA",
    "notbefore": 1700000000,
    "notafter": 2000000000,
    "pem": "-----BEGIN CERTIFICATE-----\nnot a real certificate\n",
}
CLUSTER_ISSUED = {
    "filename": "pve-ssl.pem",
    "issuer": "/CN=Example/O=Example Cluster Manager CA",
    "subject": "/CN=node.example.invalid",
    "notbefore": 1700000000,
    "notafter": 1800000000,
    "pem": "-----BEGIN CERTIFICATE-----\nnot a real certificate\n",
}
REPLACED = {
    "filename": "pveproxy-ssl.pem",
    "issuer": "/C=US/O=Example Authority",
    "subject": "/CN=node.example.invalid",
    "notbefore": 1700000000,
    "notafter": 1750000000,
    "pem": "-----BEGIN CERTIFICATE-----\nnot a real certificate\n",
}


# The three-entry shape a node with an ACME certificate actually returns,
# from a live PVE 9 cluster - names and dates replaced. The order matters:
# the API returns the root CA first and the replaced certificate last, so
# picking "the first one" or "the last one" would both be wrong on some node.
LIVE_WITH_ACME = [
    {
        "filename": "pve-root-ca.pem",
        "notafter": 2_102_400_000,
        "subject": "/CN=Example/O=Example Cluster Manager CA",
        "issuer": "/CN=Example/O=Example Cluster Manager CA",
    },
    {
        "filename": "pve-ssl.pem",
        "notafter": 1_850_000_000,
        "subject": "/CN=node.internal.invalid",
        "issuer": "/CN=Example/O=Example Cluster Manager CA",
    },
    {
        "filename": "pveproxy-ssl.pem",
        "notafter": 1_796_000_000,
        "subject": "/CN=node.example.invalid",
        "issuer": "/C=US/O=Example Authority",
    },
]


def test_a_real_node_with_a_replaced_certificate() -> None:
    """
    Test the shape a live node with an ACME certificate returns.

    The replaced certificate expires soonest and is listed last, while the
    cluster CA lasts ten years and comes first - so neither position nor
    expiry can stand in for choosing the right one.
    """
    data = parse_certificates(LIVE_WITH_ACME, "node1")

    assert data.filename == "pveproxy-ssl.pem"
    assert data.expires.timestamp() == 1_796_000_000
    assert data.issuer == "/C=US/O=Example Authority"


def test_prefers_the_certificate_that_serves_the_api() -> None:
    """Test a replaced certificate wins over the one the cluster issued."""
    data = parse_certificates([ROOT_CA, CLUSTER_ISSUED, REPLACED], "node1")

    assert data.filename == "pveproxy-ssl.pem"
    assert data.expires.timestamp() == 1750000000
    assert data.issuer == "/C=US/O=Example Authority"


def test_falls_back_to_the_cluster_issued_certificate() -> None:
    """Test the node's own certificate is used when none was replaced."""
    data = parse_certificates([ROOT_CA, CLUSTER_ISSUED], "node1")

    assert data.filename == "pve-ssl.pem"
    assert data.expires.timestamp() == 1800000000


def test_the_root_ca_alone_is_not_reported() -> None:
    """
    Test the cluster CA is ignored.

    It is valid for ten years and its expiry is not something anyone acts on,
    so a node reporting only that gets no entity rather than a misleading one.
    """
    data = parse_certificates([ROOT_CA], "node1")

    assert data.expires is UNDEFINED
    assert data.filename is None


def test_unusable_timestamp() -> None:
    """Test a certificate whose expiry cannot be read yields no value."""
    data = parse_certificates([{**CLUSTER_ISSUED, "notafter": "soon"}], "node1")

    assert data.expires is UNDEFINED


def test_empty_and_malformed_responses() -> None:
    """Test nothing usable still produces a well-formed result."""
    assert parse_certificates([], "node1").expires is UNDEFINED
    assert parse_certificates(["not a dict"], "node1").expires is UNDEFINED
    assert parse_certificates([{"no": "filename"}], "node1").expires is UNDEFINED


def test_the_certificate_itself_is_never_carried() -> None:
    """
    Test the PEM body does not reach the data model.

    It is a few kilobytes that would land in a state attribute and in every
    diagnostics dump, and it says nothing a sensor can act on.
    """
    fields = {field.name for field in dataclasses.fields(ProxmoxCertificateData)}

    assert "pem" not in fields
    assert "fingerprint" not in fields

    data = parse_certificates([REPLACED], "node1")
    assert "not a real certificate" not in str(dataclasses.asdict(data))


def test_the_node_is_recorded() -> None:
    """Test the result names the node it came from."""
    assert parse_certificates([CLUSTER_ISSUED], "node1").node == "node1"
