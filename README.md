# Proxmox VE Custom Integration Home Assistant


[Proxmox VE](https://www.proxmox.com/en/) is an open-source server virtualization environment. This integration allows you to poll various data and controls from your instance.

![image](https://user-images.githubusercontent.com/31328123/189549962-1b195b2c-a5b8-40eb-947e-74052543d804.png)

## Installation

### If you use [HACS](https://hacs.xyz/):

1. Click on HACS in the Home Assistant menu
2. Click on the 3 dots in the top right corner.
3. Select "Custom repositories"
4. Add the URL to the repository.
5. Select the Integration category.
6. Click the "ADD" button.

7. Click on HACS in the Home Assistant menu
8. Click on `Integrations`
9. Click the `EXPLORE & DOWNLOAD REPOSITORIES` button
10. Search for `Proxmox VE`
11. Click the `DOWNLOAD` button
12. Restart Home Assistant

### Manually:

1. Copy `proxmoxve` folder from [latest release](https://github.com/dougiteixeira/proxmoxve/releases/latest) to [`custom_components` folder](https://developers.home-assistant.io/docs/creating_integration_file_structure/#where-home-assistant-looks-for-integrations). in your config folder.
2. Restart Home Assistant

## Configuration

Adding Proxmox VE to your Home Assistant instance can be done via the user interface, by using this My button:

[![image](https://user-images.githubusercontent.com/31328123/189550000-6095719b-ca38-4860-b817-926b19de1b32.png)](https://my.home-assistant.io/redirect/config_flow_start?domain=proxmoxve)

### Manual configuration steps
If the above My button doesn’t work, you can also perform the following steps manually:

* Browse to your Home Assistant instance.
* In the sidebar click on  Settings.
* From the configuration menu select: Devices & Services.
* In the bottom right, click on the  Add Integration button.
* From the list, search and select “Proxmox VE”.
* Follow the instruction on screen to complete the set up.

## Proxmox Permissions

To be able to retrieve the status of VMs and containers, the user used to connect must minimally have the VM.Audit privilege.
To be able to controls the VMs and containers, the user used to connect must have the PVEVMAdmin role.
Below is a guide to how to configure a new user with the minimum required permissions.

### CREATE HOME ASSISTANT GROUP

Before creating the user, we need to create a group for the user. Privileges can be either applied to Groups or Roles.

* Click Datacenter
Open Permissions and click Groups
* Click the Create button above all the existing groups
Name the new group (e.g., HomeAssistant)
* Click Create

#### ADD GROUP PERMISSIONS TO ALL ASSETS

##### For the group to access the VMs we need to grant it the auditor role

* Click Datacenter
* Click Permissions
* Open Add and click Group Permission
* Select “/” for the path
* Select your Home Assistant group (HomeAssistant)
* Select the Auditor role (PVEAuditor)
* Make sure Propagate is checked

##### For the group to control the VMs, we need to grant the admin role.

* Click Datacenter
* Click Permissions
* Open Add and click Group Permission
* Select “/” for the path
* Select your Home Assistant group (HomeAssistant)
* Select the VM Admin role (PVEVMAdmin)
* Make sure Propagate is checked

### CREATE HOME ASSISTANT USER

Creating a dedicated user for Home Assistant, limited to only to the access just created is the most secure method. These instructions use the pve realm for the user. This allows a connection, but ensures that the user is not authenticated for SSH connections. If you use the pve realm, just be sure to add realm: pve to your configuration.

* Click Datacenter
* Open Permissions and click Users
* Click Add
* Enter a username (e.g., homeassistant)
* Set the realm to “Proxmox VE authentication server”
* Enter a secure password (it can be complex as you will only need to copy/paste it into your Home Assistant configuration)
* Select the group just created earlier (HomeAssistant) to grant access to Proxmox
* Ensure Enabled is checked and Expire is set to “never”
* Click Add

In your Home Assistant configuration, use homeassistant@pve for the username and your chosen password for the password.
