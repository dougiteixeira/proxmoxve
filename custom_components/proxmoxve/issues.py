# Copyright (c) 2019-2026
# SPDX-License-Identifier: MIT
"""
The repairs an entry raises about its resources, one per kind.

Two things go wrong per resource: the cluster does not list it, or the
credentials may not read it. Both used to be one repair per resource -
and a user without `VM.Audit` on `/vms` got one per VM, all saying the
same. Now each kind is one repair per config entry that lists the
resources concerned, rewritten as they come and go and removed when none
is left. The lists live in `hass.data`, since the entry's runtime data
does not exist yet while the coordinators take their first refresh; the
repairs are not persistent and go with the entry when it is unloaded.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

RESOURCE_ISSUES = "resource_issues"
FORBIDDEN = "forbidden"
NONEXISTENT = "nonexistent"
# What earlier versions raised per resource; persistent, so they have to
# be swept out once.
LEGACY_SUFFIXES = ("_forbiden", "_resource_nonexistent")


@dataclasses.dataclass
class ResourceLine:
    """One resource on a list: how it is shown, and what it would need."""

    label: str
    permission: str
    # The id the entry tracks it under, so a deselected resource can be
    # dropped from the list; None for cluster-wide reads.
    tracked_as: str | None = None


def _lists(hass: HomeAssistant, entry_id: str) -> dict[str, dict[str, ResourceLine]]:
    store = hass.data.setdefault(DOMAIN, {}).setdefault(RESOURCE_ISSUES, {})
    return store.setdefault(entry_id, {FORBIDDEN: {}, NONEXISTENT: {}})


def _rewrite(hass: HomeAssistant, config_entry: ConfigEntry, kind: str) -> None:
    lines = _lists(hass, config_entry.entry_id)[kind]
    issue_id = f"{config_entry.entry_id}_{kind}"
    if not lines:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        # Not persistent: the lists behind them live in memory, and setup
        # raises them again if they still apply after a restart.
        is_persistent=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=f"resources_{kind}",
        translation_placeholders={
            "user": config_entry.data.get(CONF_USERNAME, ""),
            "host": str(config_entry.data.get(CONF_HOST, "")),
            "port": str(config_entry.data.get(CONF_PORT, "")),
            "count": str(len(lines)),
            "items": "\n".join(
                f"* `{line.label}` — `{line.permission}`"
                for _, line in sorted(lines.items())
            ),
        },
    )


@callback
def note_resource(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    kind: str,
    key: str,
    line: ResourceLine | None = None,
    *,
    listed: bool,
) -> None:
    """
    Put a resource on the list of `kind`, or take it off, and rewrite the repair.

    Called with `listed=False` on every successful read as well, so it has
    to be cheap when nothing changes.
    """
    lines = _lists(hass, config_entry.entry_id)[kind]
    if listed:
        if key in lines and line is not None and lines[key] == line:
            return
        if line is None:
            return
        lines[key] = line
    else:
        if key not in lines:
            return
        del lines[key]
    _rewrite(hass, config_entry, kind)


def note_resource_threadsafe(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    kind: str,
    key: str,
    line: ResourceLine | None = None,
    *,
    listed: bool,
) -> None:
    """Do the same from an executor thread - the poll runs in one."""
    hass.loop.call_soon_threadsafe(
        lambda: note_resource(hass, config_entry, kind, key, line, listed=listed)
    )


@callback
def forget_untracked(
    hass: HomeAssistant, config_entry: ConfigEntry, still_tracked: set[str]
) -> None:
    """
    Drop resources this setup no longer tracks from both lists.

    The "does not exist" line tells you to remove the resource in the
    options. Doing that reloads the entry, and setup then never looks at
    the resource again - so nothing would take the line off. A resource
    deselected while its read was refused is the same for the other list.
    Cluster-wide reads have no tracked id and stay until they succeed.
    """
    for kind, lines in _lists(hass, config_entry.entry_id).items():
        stale = [
            key
            for key, line in lines.items()
            if line.tracked_as is not None and line.tracked_as not in still_tracked
        ]
        if not stale:
            continue
        for key in stale:
            del lines[key]
        _rewrite(hass, config_entry, kind)


@callback
def sweep_legacy_issues(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Delete the per-resource repairs earlier versions left in the registry."""
    prefix = f"{config_entry.entry_id}_"
    registry = ir.async_get(hass)
    for domain, issue_id in list(registry.issues):
        if (
            domain == DOMAIN
            and issue_id.startswith(prefix)
            and issue_id.endswith(LEGACY_SUFFIXES)
            # A refused button press has a repair of its own, still in use.
            and not issue_id.endswith("_command_forbiden")
        ):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def forget_entry(hass: HomeAssistant, entry_id: str) -> None:
    """
    Drop the lists and the repairs of an entry that is unloaded.

    A reload raises them again where they still apply; a resource
    deselected in the options - which is what the "not found" repair asks
    for - is not looked at again and so stays off.
    """
    hass.data.get(DOMAIN, {}).get(RESOURCE_ISSUES, {}).pop(entry_id, None)
    for kind in (FORBIDDEN, NONEXISTENT):
        ir.async_delete_issue(hass, DOMAIN, f"{entry_id}_{kind}")
