[← README](https://github.com/dougiteixeira/proxmoxve#readme) · [Entities](entities.md) · [Actions](actions.md) · [Hardware sensors](hardware-sensors.md) · [Permissions](permissions.md) · [Behaviour](behaviour.md) · [Troubleshooting](troubleshooting.md) · [Compared with core](compared-to-core.md)

# Proxmox permissions

> [!IMPORTANT]  
> It is necessary to reload the integration after changing user/token permissions in Proxmox.

To be able to obtain each type of integration information, the user used to connect must have the corresponding privilege.

It is not necessary to include all of the permission roles below, this will depend on your use of the integration.

The integration will create a repair for each resource that is exposed in the integration configuration but is not accessible by the user, indicating the path and privilege necessary to access it.

Control buttons are only created for actions the user may actually perform: at setup the integration reads the effective privileges of its credentials (`GET /access/permissions`) and leaves out, for instance, the `Reboot` button of a node without `Sys.PowerMgmt`, the `Create snapshot` button of a guest without `VM.Snapshot`, or the `Start` button of a guest without `VM.PowerMgmt`. A button that could only ever fail is not worth having. Grant the privilege and reload the integration to get the button back. Should the privileges not be readable at all, every button is created as before.

When executing a command, if the user does not have the necessary permission, a repair will be created indicating the path and privilege necessary to execute it.

> [!CAUTION]
> The permissions suggested in this documentation and in the created repairs are informative, the responsibility for assessing the risks involved in assigning permissions to the user is the sole responsibility of the user.

## Suggestion for creating permission roles for use with integration

Below is a summary of the permissions for each integration feature. I suggest you create the roles below to make it easier to assign only the necessary permissions to the user.

|Purpose of Permission|Access Type|Role (name suggestion)|Privilegies|
|---|---|---|---|
|Get data from nodes, VM, CT and storages|Read only|HomeAssistant.Audit|VM.Audit, Sys.Audit and Datastore.Audit|
|Perform commands on the node (shutdown, restart, start all, shutdown all)|Management permission|HomeAssistant.NodePowerMgmt|Sys.PowerMgmt|
|Get information about available package updates to display on sensors (integration does not trigger the update)|Management permission|HomeAssistant.Update|Sys.Modify|
|Perform commands on VM/CT (start, shutdown, restart, suspend, resume and hibernate)|Management permission|HomeAssistant.VMPowerMgmt|VM.PowerMgmt|
|**(Optional, separate user/token — see [Cluster HA Administration](entities.md#cluster-ha-administration-advanced-optional))** Arm/Disarm HA and read the HA-managed resource list and cluster HA status, root-scoped (`/`)|Cluster-wide management permission|HomeAssistant.ClusterHA|Sys.Console, Sys.Audit|

## Create Home Assistant Group

Before creating the user, we need to create a group for the user.
Privileges can be either applied to Groups or Roles.

1. Click `Datacenter`
2. Open `Permissions` and click `Groups`
3. Click the `Create` button above all the existing groups
4. Name the new group (e.g., `HomeAssistant`)
5. Click `Create`

## Add Group Permissions to all Assets

1. Click `Datacenter`
2. Click `Permissions`
3. Open `Add` and click `Group Permission`
4. Select the path of the resource you want to authorize the user to access. To enable all features select `/`
5. Select your Home Assistant group (`HomeAssistant`)
6. Select the role according to the table above (you must add a permission for each role in the table).
7. Make sure `Propagate` is checked

## Create Home Assistant User

Creating a dedicated user for Home Assistant, limited to only to the access just created is the most secure method. These instructions use the `pve` realm for the user. This allows a connection, but ensures that the user is not authenticated for SSH connections.

1. Click `Datacenter`
2. Open `Permissions` and click `Users`
3. Click `Add`
4. Enter a username (e.g.,` homeassistant`)
5. Set the realm to "Proxmox VE authentication server"
6. Enter a secure password (it can be complex as you will only need to copy/paste it into your Home Assistant configuration)
7. Select the group just created earlier (`HomeAssistant`) to grant access to Proxmox
8. Ensure `Enabled` is checked and `Expire` is set to "never"
9. Click `Add`

## Create token for user (recommended)

Creating a dedicated user token for Home Assistant, limited only to the newly created access, is the most recommended method.

1. Click `Datacenter`
2. Open `Permissions` and click `API Tokens`
3. Click `Add`
4. Select the user linked to the token
5. Enter a name for the token in the `Token ID` field (e.g.,` homeassistant`)
6. Decide how the token gets its permissions — this is the step most setups get wrong, see the note below:
   - **Uncheck `Privilege Separation`** and the token simply has the permissions of its user. Nothing else to do.
   - **Leave it checked** and the token has *no permissions of its own*, whatever its user may do. You then have to add the token itself (`homeassistant@pve!homeassistant`) to the same permission paths as the user, under `Datacenter → Permissions → Add → API Token Permission`.
7. Select the Never option in the `Expire` field
8. Ensure `Enabled` is checked and `Expire` is set to "never"
9. Click `Add`
10. Copy the secret token value

> [!WARNING]
> After closing the popup it is not possible to recover this value, if you lose the token value you must create a new token.

> [!IMPORTANT]
> **A token with `Privilege Separation` does not inherit anything from its user.** If the setup lists only the node and none of your VMs or containers, or the log says `Node <name> unable to be found`, while the user itself has every permission the table above asks for, this is why: the permissions sit on the user, the token has none. Either uncheck `Privilege Separation` on the token, or grant the token the same paths and roles as the user. Reload the integration afterwards.

> [!TIP]
> In your Home Assistant configuration, enter the token's **name** — `homeassistant` from a `Token ID` of `homeassistant@pve!homeassistant` — in the `Token name` field. The full id is accepted as well.
