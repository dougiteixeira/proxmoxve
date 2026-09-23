# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""Tests for moving to another node of the cluster when the configured one is gone."""

from unittest.mock import MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from proxmoxer import AuthenticationError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from requests.exceptions import ConnectionError as RequestsConnectionError

from custom_components.proxmoxve.api import ProxmoxClient
from custom_components.proxmoxve.const import (
    CONF_CLUSTER_HOSTS,
    COORDINATORS,
    PROXMOX_CLIENT,
    ProxmoxType,
)

from .fake_api import NODE, FakeProxmox

CONFIGURED = "192.168.10.101"
LEARNED = ("192.0.2.10", "192.0.2.11")


def _client() -> ProxmoxClient:
    """Return a token client for the configured host, built without network."""
    client = ProxmoxClient(
        host=CONFIGURED,
        user="homeassistant",
        password="secret",  # noqa: S106 - invented
        token_name="homeassistant",  # noqa: S106 - not a secret
        realm="pve",
        verify_ssl=False,
    )
    client.build_client()
    return client


def test_learned_hosts_come_after_the_configured_one() -> None:
    """Test the configured host stays first and repeats are dropped."""
    client = _client()

    client.learn_hosts([*LEARNED, CONFIGURED, LEARNED[0], "", None])

    assert client.hosts == (CONFIGURED, *LEARNED)
    assert client.host == CONFIGURED


def test_failover_moves_to_the_first_host_that_answers() -> None:
    """Test a host that refuses is skipped and the next one taken."""
    client = _client()
    client.learn_hosts(LEARNED)
    before = client.get_api_client()

    def build(host: str) -> MagicMock:
        api = MagicMock(name=host)
        if host == LEARNED[0]:
            api.version.get.side_effect = RequestsConnectionError("refused")
        return api

    with patch.object(client, "_build", side_effect=build):
        assert client.failover(client.generation) is True

    assert client.host == LEARNED[1]
    assert client.get_api_client() is not before
    assert client.generation == 1


def test_failover_with_nothing_else_answering_reports_that() -> None:
    """Test the original failure stands when no other node answers."""
    client = _client()
    client.learn_hosts(LEARNED)

    def build(host: str) -> MagicMock:
        api = MagicMock(name=host)
        api.version.get.side_effect = AuthenticationError("code: 595")
        return api

    with patch.object(client, "_build", side_effect=build):
        assert client.failover(client.generation) is False

    assert client.host == CONFIGURED
    assert client.generation == 0


def test_a_single_host_has_nowhere_to_go() -> None:
    """Test a client that learned nothing does not pretend to fail over."""
    client = _client()

    assert client.failover(client.generation) is False


def test_a_poll_that_saw_the_old_generation_does_not_switch_again() -> None:
    """
    Test the second of two concurrent failures does not move a second time.

    Every coordinator polls on its own, so several hit the dead host at once.
    The first one through switches; the others show the generation they saw
    before their request and are simply told a working host is in place.
    """
    client = _client()
    client.learn_hosts(LEARNED)
    seen = client.generation

    with patch.object(client, "_build", side_effect=lambda host: MagicMock(name=host)):
        assert client.failover(seen) is True
        assert client.host == LEARNED[0]
        assert client.failover(seen) is True

    assert client.host == LEARNED[0]
    assert client.generation == 1


async def test_the_cluster_stays_in_home_assistant_when_the_host_goes(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the reported problem: one host down took the whole cluster out.

    Everything goes through the configured host's pveproxy. Once it is
    gone, the client moves to a node it learned from `cluster/status` and
    the coordinators keep reading - through the object the client is using
    now, not the one they were built with.
    """
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()
    assert current_entry.state is ConfigEntryState.LOADED
    client: ProxmoxClient = current_entry.runtime_data[PROXMOX_CLIENT]
    assert client.hosts == (CONFIGURED, "192.0.2.10", "192.0.2.11")
    node = current_entry.runtime_data[COORDINATORS][f"{ProxmoxType.Node}_{NODE}"]
    built_with = node._proxmox  # noqa: SLF001

    fake_api.dead_hosts.add(CONFIGURED)
    await node.async_refresh()

    assert node.last_update_success
    assert client.host == "192.0.2.10"
    assert node.proxmox is client.get_api_client()
    assert node.proxmox is not built_with
    # The dead host was tried once for this poll, then the fallback answered.
    assert fake_api.hosts_seen[-1] == "192.0.2.10"


async def test_without_any_other_node_the_failure_is_reported(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a single node that goes away still fails the update, as before."""
    del fake_api.routes["cluster/status"]
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()
    client: ProxmoxClient = current_entry.runtime_data[PROXMOX_CLIENT]
    assert client.hosts == (CONFIGURED,)
    node = current_entry.runtime_data[COORDINATORS][f"{ProxmoxType.Node}_{NODE}"]

    fake_api.dead_hosts.add(CONFIGURED)
    await node.async_refresh()

    assert not node.last_update_success
    assert client.host == CONFIGURED


async def test_the_entry_remembers_the_cluster_for_the_next_start(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test the addresses read from `cluster/status` are kept in the entry."""
    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert current_entry.data[CONF_CLUSTER_HOSTS] == list(LEARNED)


async def test_a_start_while_the_configured_host_is_down(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """
    Test the reported problem: a restart took the entry out until the node was back.

    The fallback was learned from `cluster/status` once a connection stood,
    and was forgotten with the session. Home Assistant restarting while the
    configured node is down - a rack rebuild, in the report - then had
    nowhere to go, because setup begins against the configured host and
    nothing else was known.
    """
    hass.config_entries.async_update_entry(
        current_entry,
        data={**current_entry.data, CONF_CLUSTER_HOSTS: list(LEARNED)},
    )
    fake_api.dead_hosts.add(CONFIGURED)

    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert current_entry.state is ConfigEntryState.LOADED
    client: ProxmoxClient = current_entry.runtime_data[PROXMOX_CLIENT]
    assert client.host == LEARNED[0]
    # Still the configured host's entry; it is where setup goes again once
    # the node is back, and nothing was rewritten behind the user's back.
    assert current_entry.data[CONF_HOST] == CONFIGURED


async def test_a_start_with_nothing_remembered_waits_as_before(
    hass: HomeAssistant, fake_api: FakeProxmox, current_entry: MockConfigEntry
) -> None:
    """Test a host that is down and no known cluster still leaves setup retrying."""
    fake_api.dead_hosts.add(CONFIGURED)

    await hass.config_entries.async_setup(current_entry.entry_id)
    await hass.async_block_till_done()

    assert current_entry.state is ConfigEntryState.SETUP_RETRY


def test_a_single_host_is_not_read_twice() -> None:
    """
    Test nothing extra is asked of a setup that has nowhere to fall back to.

    The `version` read that proves a host is there is worth one request
    where it can save the entry; where the cluster is one node, or was
    never readable, it would only be a second call for the same answer.
    """
    client = _client()
    with patch.object(client, "_build", side_effect=lambda host: MagicMock(name=host)):
        client.build_client()
        assert client.get_api_client().version.get.call_count == 0

        client.learn_hosts(LEARNED)
        client.build_client()
        assert client.get_api_client().version.get.call_count == 1
