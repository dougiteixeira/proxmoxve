# Blueprints

Here you will find some blueprints that help you to solve small integration bugs:

## When the integration does not recover after the host goes offline for an extended period of time and then comes back online:

How it works is to verify that the Proxmox node status sensor is running when the Proxmox host connectivity sensor is changed from Disconnected (`off`) to Connected (`on`). If the status sensor is `unavailable` the integration reload will be triggered.
To avoid unnecessary reloads, a time of 1 minute is waited after the host goes online to execute the automation.

### Previous steps:

To use this blueprint you need to create a binary sensor in your Home Assistant using the Ping integration ([see documentation here](https://www.home-assistant.io/integrations/ping/#binary-sensor)), follow the steps below:

* Include the code below in your configuration file (`configuration.yaml`):
  ```
    - platform: ping
      host: 10.10.10.10 # Change to the IP address of your Proxmox host
      name: Proxmox host connectivity
      count: 2
      scan_interval: 30
  ```
* Change to the IP address of your Proxmox host in the file.
* Save the file.
* Restart Home Assistant.

### Importing via My Home Assistant:
* Click this button to import:
  
  [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fdougiteixeira%2Fproxmoxve%2Fnew%2Fdougiteixeira-patch-1%2Fblueprints)

#### Or do the import manually:

* Go to [Settings > Automations & Scenes > Blueprints](https://my.home-assistant.io/redirect/blueprints/).
* Select the blue Import Blueprint button in the bottom right.
* A new dialog will pop-up asking you for the URL.
* Enter the URL and select Preview.
* This will load the blueprint and show a preview in the import dialog.
* You can change the name and finish the import.
* The blueprint can now be used for creating automations.

### Adding automation via blueprint:

* Go to [Settings > Automations & Scenes > Blueprints](https://my.home-assistant.io/redirect/blueprints/).
* Click on the imported blueprint (Proxmox - Reload Config Entry)
* Select Proxmox host connectivity entity (binary sensor created with Ping integration)
* Select Proxmox node status entity (Binary sensor Status node)

