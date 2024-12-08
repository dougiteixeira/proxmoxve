# Send CPU temperature information to Home Assistant

This has nothing to do with this integration, it's just one of several possible ways to publish your CPU temperature to Home Assistant.

You should use this as an example and adjust to your use case.

_There will be no support for issues with this alternative._

### Install `lm-sensors`

`apt-get install lm-sensors`

### Create script in your server Proxmox:

`nano /usr/temp_ha_post`

```
#! /bin/bash
url1=http://10.10.10.xxx:8123/api/states/sensor.proxmox_cpu_temperature
token1=xxxxx

temp=$(sensors | grep -e "°C" | grep "Core" | awk -F "+" '{ print $2 }' | awk -F "." '{ print $1 }' | sort | tail -n1);
curl -X POST -H "Authorization: Bearer $token1" -H 'Content-type: application/json' --data "{\"state\":\"$temp\",\"attributes\": {\"friendly_name\":\"Proxmox CPU Temperature\",\"icon\":\"mdi:cpu-64-bit\",\"state_class\":\"measurement\",\"unit_of_measurement\":\"°C\",\"device_class\":\"temperature\"}}" $url1;
```

#### Give the file execute permission:

`chmod +x /usr/temp_ha_post`

#### Test the script (see if there are errors and if the entity was created in Home Assistant):

`/usr/temp_ha_post`

### Configure a cron schedule (CRON):

`crontab -e`

#### Add after the last line of the file:

`*/1 * * * * /usr/temp_ha_post`

#### Restart the cron service:

`service cron restart`
