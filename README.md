# Proxmox VE Custom Integration Home Assistant


[Proxmox VE](https://www.proxmox.com/en/) is an open-source server virtualization environment. This integration allows you to poll various data and controls from your instance.

After configuring this integration, the following information is available:

 - Binary sensor entities with the status of node and selected virtual machines/containers.
 - Sensor entities of the selected node and virtual machines/containers. Some sensors are created disabled by default, you can enable them by accessing the entity's configuration.
 - Entities button to control selected virtual machines/containers (see about Proxmox user permissions below). By default, the entities buttons to control virtual machines/containers are created disabled, [see how to enable them here](https://github.com/dougiteixeira/proxmoxve/#some-entities-are-disabled-by-default-including-control-buttons-see-below-how-to-enable-them).

![image](https://user-images.githubusercontent.com/31328123/189549962-1b195b2c-a5b8-40eb-947e-74052543d804.png)

## Install

### Installation via HACS

Have [HACS](https://hacs.xyz/) installed, this will allow you to update easily.

* Adding Proxmox VE to HACS can be using this button:

[![image](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dougiteixeira&repository=proxmoxve&category=integration)

(If the button above doesn't work, add `https://github.com/dougiteixeira/proxmoxve` as a custom repository of type Integration in HACS.)
* Click Install on the `Proxmox VE` integration.
* Restart the Home Assistant.

### Manual installation

- Copy `proxmoxve`  folder from [latest release](https://github.com/dougiteixeira/proxmoxve/releases/latest) to [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations) in your config directory.
- Restart the Home Assistant.

## Configuration

Adding Proxmox VE to your Home Assistant instance can be done via the UI using this button:

[![image](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=proxmoxve)

### Manual Configuration

If the button above doesn't work, you can also perform the following steps manually:

* Navigate to your Home Assistant instance.
* In the sidebar, click Settings.
* From the Setup menu, select: Devices & Services.
* In the lower right corner, click the Add integration button.
* In the list, search and select `Proxmox VE`.
* Follow the on-screen instructions to complete the setup.

## Debugging

To enable debug for Proxmox VE integration, add following to your `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.proxmoxve: debug
```

## Proxmox Permissions

To be able to retrieve the status of VMs and containers, the user used to connect must minimally have the `VM.Audit` privilege. To be able to controls the VMs and containers, the user used to connect must have the `PVEVMAdmin` role. Below is a guide to how to configure a new user with the minimum required permissions.

### Create Home Assistant Group

Before creating the user, we need to create a group for the user.
Privileges can be either applied to Groups or Roles.

1. Click `Datacenter`
2. Open `Permissions` and click `Groups`
3. Click the `Create` button above all the existing groups
4. Name the new group (e.g., `HomeAssistant`)
5. Click `Create`

### Add Group Permissions to all Assets

#### For the group to access the VMs we need to grant it the auditor role
1. Click `Datacenter`
2. Click `Permissions`
3. Open `Add` and click `Group Permission`
4. Select "/" for the path
5. Select your Home Assistant group (`HomeAssistant`)
6. Select the Auditor role (`PVEAuditor`)
7. Make sure `Propagate` is checked

#### For the group to control the VMs, we need to grant the admin role.
1. Click `Datacenter`
2. Click `Permissions`
3. Open `Add` and click `Group Permission`
4. Select "/" for the path
5. Select your Home Assistant group (`HomeAssistant`)
6. Select the VM Admin role (`PVEVMAdmin`)
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
  
   1) Go to the page for the device you want to enable the button (or sensor).

      ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/4e3f9b7d-e935-4fc5-bdd3-3329ef9b90a8)
   
   2) Click +x entities not show

      ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/0240d2ed-efac-4c59-9def-e721a44dde90)
   
   3) Click on the entity you want to enable and click on settings (on the gear icon):

      ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/e1bd2fb2-6fb5-4919-88c1-8056b7435f87)
   
   4) Click the Enable button at the top of the dialog:

      ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/1a8205e4-a779-4a01-922d-5d147e8e5766)
   
   5) Wait a while (approximately 30 seconds) for the entity to be enabled. If you don't want to wait, just reload the configuration entry on the integration page.

      ![image](https://github.com/dougiteixeira/proxmoxve/assets/31328123/33edd547-8c55-44eb-b0b9-5036317bf077)
   
   For the entity to appear enabled on the device page, it may be necessary to refresh the page.
   </details>
