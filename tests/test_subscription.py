# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for reading a node's subscription state."""

import dataclasses

from homeassistant.helpers.typing import UNDEFINED

from custom_components.proxmoxve.coordinator import (
    SUBSCRIPTION_STATES,
    parse_subscription,
)
from custom_components.proxmoxve.models import ProxmoxSubscriptionData
from custom_components.proxmoxve.sensor import PROXMOX_SENSOR_SUBSCRIPTION

# Shaped like `GET /nodes/<node>/subscription` on a node without one. The real
# response also carries `serverid`; with a subscription it adds `key`,
# `signature`, `regdate` and `sockets`. Values here are invented.
WITHOUT_SUBSCRIPTION = {
    "message": "There is no subscription key",
    "serverid": "0000000000000000000000000000000A",
    "status": "notfound",
    "url": "https://www.example.invalid/pricing",
}

WITH_SUBSCRIPTION = {
    "checktime": 1700000000,
    "key": "pve4c-0000000000",
    "level": "c",
    "nextduedate": "2027-01-31",
    "productname": "Proxmox VE Community Subscription 4 CPUs/year",
    "regdate": "2026-01-31 00:00:00",
    "serverid": "0000000000000000000000000000000A",
    "signature": "not a real signature",
    "sockets": 4,
    "status": "active",
}


def test_no_subscription() -> None:
    """Test the common case reads as a state rather than an error."""
    data = parse_subscription(WITHOUT_SUBSCRIPTION, "node1")

    assert data.status == "notfound"
    assert data.level is None
    assert data.product is None
    assert data.next_due is None


def test_an_active_subscription() -> None:
    """Test the details worth seeing are carried."""
    data = parse_subscription(WITH_SUBSCRIPTION, "node1")

    assert data.status == "active"
    assert data.level == "c"
    assert data.next_due == "2027-01-31"
    assert data.product.startswith("Proxmox VE Community")


def test_identifying_fields_are_never_carried() -> None:
    """
    Test the key, server id and signature do not reach the data model.

    They identify the machine and the subscription itself, and would end up
    in a state attribute and in every diagnostics dump.
    """
    fields = {field.name for field in dataclasses.fields(ProxmoxSubscriptionData)}
    assert not fields & {"key", "serverid", "signature", "sockets", "regdate"}

    dumped = str(dataclasses.asdict(parse_subscription(WITH_SUBSCRIPTION, "node1")))
    assert "pve4c-0000000000" not in dumped
    assert "0000000000000000000000000000000A" not in dumped
    assert "not a real signature" not in dumped


def test_an_unknown_status_is_dropped() -> None:
    """Test a state outside the documented set never reaches the enum."""
    data = parse_subscription({**WITHOUT_SUBSCRIPTION, "status": "renewing"}, "node1")

    assert data.status is UNDEFINED


def test_a_response_without_a_status() -> None:
    """Test a response carrying no status at all yields no value."""
    assert parse_subscription({}, "node1").status is UNDEFINED


def test_sensor_options_match_the_parser() -> None:
    """Test the enum sensor accepts exactly the states the parser can emit."""
    description = PROXMOX_SENSOR_SUBSCRIPTION[0]

    assert set(description.options) == SUBSCRIPTION_STATES
