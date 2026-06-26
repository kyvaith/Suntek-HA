<p align="center">
  <img src="custom_components/suntek_lte_camera/brand/logo.png" alt="Suntek LTE Camera" width="160">
</p>

<h1 align="center">Suntek-HA</h1>

<p align="center">
  <a href="https://www.home-assistant.io/"><img alt="Home Assistant" src="https://img.shields.io/badge/Home%20Assistant-custom%20integration-41BDF5?logo=homeassistant&logoColor=white"></a>
  <a href="https://hacs.xyz/"><img alt="HACS" src="https://img.shields.io/badge/HACS-custom-orange"></a>
  <img alt="Trail camera" src="https://img.shields.io/badge/trail%20camera-LTE-green">
  <a href="https://github.com/kyvaith/Suntek-HA/releases"><img alt="Release" src="https://img.shields.io/github/v/release/kyvaith/Suntek-HA?display_name=tag"></a>
</p>

A Home Assistant custom integration for Suntek LTE trail cameras used for outdoor monitoring, wildlife observation, remote plots, feeders, and forest camera setups.

## Features

- Adds a standard Home Assistant camera entity with a dashboard preview tile.
- Adds a dedicated `Suntek Camera` dashboard card.
- Wakes the LTE camera automatically whenever Home Assistant requests the camera preview.
- Lets you add the camera from the Home Assistant UI with login, password, and camera selection.
- Handles the Suntek cloud password hash used by the mobile app.
- Validates the camera against the Suntek cloud during setup.
- Shows the Suntek cloud connection separately from the camera status.
- Adds camera status sensors for signal, battery, SD storage, position, model, firmware, last communication, temperature, APN, video resolution, video length, upload target, and schedule.
- Adds a wake-up button for the camera.
- Adds a cloud media sync button and optional scheduled backup for cloud photos and videos.
- Provides the `suntek_lte_camera.wakeup`, `suntek_lte_camera.refresh`, and `suntek_lte_camera.sync_cloud_media` services.

## Installation With HACS

1. Open HACS in Home Assistant.
2. Open the menu and choose Custom repositories.
3. Add this repository URL:

```text
https://github.com/kyvaith/Suntek-HA
```

4. Select Integration as the category.
5. Install Suntek LTE Camera.
6. Restart Home Assistant.

## Manual Installation

Copy this directory:

```text
custom_components/suntek_lte_camera
```

to your Home Assistant config directory:

```text
config/custom_components/suntek_lte_camera
```

Restart Home Assistant after copying the files.

## Configuration

In Home Assistant, go to Settings, Devices & services, Add integration, and search for Suntek LTE Camera.

The setup flow asks for:

- Login / IMEI
- PIN / password
- Camera selection

Enter the plain PIN/password from the SuntekCam app or camera instructions. The integration asks the Suntek cloud for the matching password hash and falls back to MD5 hashing when needed.

After setup, Home Assistant creates the camera entity, cloud connection sensor, camera status sensors, wake-up button, and cloud media sync button for the selected Suntek LTE trail camera.

The camera preview uses the newest JPEG image available from the Suntek cloud file list. Opening the preview also sends the wake-up command automatically, with a cooldown to avoid repeated wake-up requests.

The cloud connection binary sensor only means that the Suntek command endpoint responded. The real camera information is exposed through the camera status sensors, based on the last status payload returned by the Suntek cloud.

## Cloud Media Backup

Use the `Sync cloud media` button or call the `suntek_lte_camera.sync_cloud_media` service to copy cloud photos and videos into Home Assistant local media.

Files are saved under:

```text
media/suntek_lte_camera/<camera name>/
```

They can be browsed from Home Assistant Media as local media after synchronization.

Scheduled backup is available in the integration options:

- Enable scheduled cloud media backup
- Cloud media backup interval minutes
- Cloud media backup file limit
- Include videos in scheduled backup

Scheduled backup is disabled by default so the integration does not download large video files unexpectedly.

## Dashboard Card

After restarting Home Assistant, add the `Suntek Camera` card from the dashboard card picker.

The integration registers the card resource automatically when Home Assistant dashboards use storage mode.

If the card does not appear in the picker, add this JavaScript module resource in Home Assistant dashboards:

```text
/suntek_lte_camera/frontend/suntek-camera-card.js?v=0.4.0
```

Manual YAML example:

```yaml
type: custom:suntek-camera-card
entity: camera.your_suntek_camera
cloud_entity: binary_sensor.your_suntek_camera_cloud_connection
signal_entity: sensor.your_suntek_camera_signal
battery_entity: sensor.your_suntek_camera_battery
sd_entity: sensor.your_suntek_camera_sd_storage
temperature_entity: sensor.your_suntek_camera_temperature
last_wakeup_entity: sensor.your_suntek_camera_last_wakeup
last_media_sync_entity: sensor.your_suntek_camera_last_media_sync
sync_button_entity: button.your_suntek_camera_sync_cloud_media
```
