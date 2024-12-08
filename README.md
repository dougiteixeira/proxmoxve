# Proxmox VE Custom Integration Home Assistant

![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/dfec7426-852d-41ea-b6c1-9bfd8cd1e8a8)

[Proxmox VE](https://www.proxmox.com/en/) is an open-source server virtualization environment. This integration allows you to poll various data and controls from your instance.

This integration started as improvements to the [Home Assistant core's Proxmox VE integration](https://www.home-assistant.io/integrations/proxmoxve/), but I'm new to programming and couldn't meet all of the core's code requirements. So I decided to keep it as a custom integration. Therefore, when installing this, the core integration will be replaced.

After configuring this integration, the following information is available:

- Binary sensor entities with the status of node and selected virtual machines/containers.
- Sensor entities of the selected node and virtual machines/containers. Some sensors are created disabled by default, you can enable them by accessing the entity's configuration.
- Entities button to control selected virtual machines/containers (see about Proxmox user permissions below). By default, the entities buttons to control virtual machines/containers are created disabled, [see how to enable them here](https://github.com/dougiteixeira/proxmoxve/#some-entities-are-disabled-by-default-including-control-buttons-see-below-how-to-enable-them).

> [!IMPORTANT]
> See the section on Proxmox user permissions [here](https://github.com/dougiteixeira/proxmoxve#proxmox-permissions).

## Install

### Installation via HACS

Have [HACS](https://hacs.xyz/) installed, this will allow you to update easily.

- Adding Proxmox VE to HACS can be using this button:

[![image](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dougiteixeira&repository=proxmoxve&category=integration)

(If the button above doesn't work, add `https://github.com/dougiteixeira/proxmoxve` as a custom repository of type Integration in HACS.)

- Click Install on the `Proxmox VE` integration.
- Restart the Home Assistant.

### Manual installation

- Copy `proxmoxve` folder from [latest release](https://github.com/dougiteixeira/proxmoxve/releases/latest) to [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations) in your config directory.
- Restart the Home Assistant.

## Configuration

Adding Proxmox VE to your Home Assistant instance can be done via the UI using this button:

[![image](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=proxmoxve)

You can either use password or token based authentication. For user based authentication leave the
token name field empty and make sure to set the correct realm to pve, pam or other. You can find this value
in Proxmox under Datacenter -> Permissions -> Users -> Realm column. If you want to use token based
authentication, fill the token name in the corresponding input field and put your token secret in the password field.

### Manual Configuration

If the button above doesn't work, you can also perform the following steps manually:

- Navigate to your Home Assistant instance.
- In the sidebar, click Settings.
- From the Setup menu, select: Devices & Services.
- In the lower right corner, click the Add integration button.
- In the list, search and select `Proxmox VE`.
- Follow the on-screen instructions to complete the setup.

## Debugging

To enable debug for Proxmox VE integration, add following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.proxmoxve: debug
```

## Example screenshot:

<details><summary>Here are some screenshots of the integration</summary>

- Node
  ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/e371b34e-0449-499f-878b-b5baacee8a5e)

- VM (QEMU)
  ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/8213b877-8b23-4c4a-917b-04f27bb3a886)

- Storage
  ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/fb290802-95d7-4dcc-8538-d31636a2f6f8)

- Physical disks
![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/f6174806-0ba8-4f60-ada7-cf5f29a1f629)
</details>

## Proxmox Permissions

> [!IMPORTANT]
> It is necessary to reload the integration after changing user/token permissions in Proxmox.

To be able to obtain each type of integration information, the user used to connect must have the corresponding privilege.

It is not necessary to include all of the permission roles below, this will depend on your use of the integration.

The integration will create a repair for each resource that is exposed in the integration configuration but is not accessible by the user, indicating the path and privilege necessary to access it.

When executing a command, if the user does not have the necessary permission, a repair will be created indicating the path and privilege necessary to execute it.

> [!CAUTION]
> The permissions suggested in this documentation and in the created repairs are informative, the responsibility for assessing the risks involved in assigning permissions to the user is the sole responsibility of the user.

### Suggestion for creating permission roles for use with integration

Below is a summary of the permissions for each integration feature. I suggest you create the roles below to make it easier to assign only the necessary permissions to the user.

| Purpose of Permission                                                                                           | Access Type           | Role (name suggestion)      | Privilegies                             |
| --------------------------------------------------------------------------------------------------------------- | --------------------- | --------------------------- | --------------------------------------- |
| Get data from nodes, VM, CT and storages                                                                        | Read only             | HomeAssistant.Audit         | VM.Audit, Sys.Audit and Datastore.Audit |
| Perform commands on the node (shutdown, restart, start all, shutdown all)                                       | Management permission | HomeAssistant.NodePowerMgmt | Sys.PowerMgmt                           |
| Get information about available package updates to display on sensors (integration does not trigger the update) | Management permission | HomeAssistant.Update        | Sys.Modify                              |
| Perform commands on VM/CT (start, shutdown, restart, suspend, resume and hibernate)                             | Management permission | HomeAssistant.VMPowerMgmt   | VM.PowerMgmt                            |

### Create Home Assistant Group

Before creating the user, we need to create a group for the user.
Privileges can be either applied to Groups or Roles.

1. Click `Datacenter`
2. Open `Permissions` and click `Groups`
3. Click the `Create` button above all the existing groups
4. Name the new group (e.g., `HomeAssistant`)
5. Click `Create`

### Add Group Permissions to all Assets

1. Click `Datacenter`
2. Click `Permissions`
3. Open `Add` and click `Group Permission`
4. Select the path of the resource you want to authorize the user to access. To enable all features select `/`
5. Select your Home Assistant group (`HomeAssistant`)
6. Select the role according to the table above (you must add a permission for each role in the table).
7. Make sure `Propagate` is checked

### Create Home Assistant User

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

In your Home Assistant configuration, use `homeassistant@pve` for the username and your chosen password for the password.

## Some entities are disabled by default (including control buttons), see below how to enable them.

 <details><summary>A step by step to enable entities</summary>

1.  Go to the page for the device you want to enable the button (or sensor).

    ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/4e3f9b7d-e935-4fc5-bdd3-3329ef9b90a8)

2.  Click +x entities not show

    ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/0240d2ed-efac-4c59-9def-e721a44dde90)

3.  Click on the entity you want to enable and click on settings (on the gear icon):

    ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/e1bd2fb2-6fb5-4919-88c1-8056b7435f87)

4.  Click the Enable button at the top of the dialog:

    ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/1a8205e4-a779-4a01-922d-5d147e8e5766)

5.  Wait a while (approximately 30 seconds) for the entity to be enabled. If you don't want to wait, just reload the configuration entry on the integration page.

    ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/33edd547-8c55-44eb-b0b9-5036317bf077)

For the entity to appear enabled on the device page, it may be necessary to refresh the page.

   </details>

## Translations

You can help by adding missing translations when you are a native speaker. Or add a complete new language when there is no language file available.

Proxmox VE Custom Integration uses Crowdin to make contributing easy.

### Changing or adding to existing language

First register and join the translation project:

- If you don’t have a Crowdin account yet, create one at https://crowdin.com
- Go to the [Proxmox VE Custom Integration project page](https://crowdin.com/project/proxmoxve-homeassistant)
- Click Join.

Next translate a string:

- Select the language you want to contribute to from the dashboard.
- Click Translate All.
- Find the string you want to edit, missing translation are marked red.
- Fill in or modify the translation and click Save.
- Repeat for other translations.

### Adding a new language

[Create an Issue](https://github.com/dougiteixeira/proxmoxve/issues/new?template=new_language_request.yml&title=New+language) requesting a new language. We will do the necessary work to add the new translation to the integration and Crowdin site, when it's ready for you to contribute we'll comment on the issue you raised.
