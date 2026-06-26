<p align="center">
  <img src="https://sourcing-media.hktdc.com/original-file/da3e08e25338439faae35895ac1d3a3c?bucket=PUBLIC_ACCESS_MEDIA_BUCKET" alt="Suntek" width="220">
</p>

<h1 align="center">Suntek-HA</h1>

<p align="center">
  <a href="https://www.home-assistant.io/"><img alt="Home Assistant" src="https://img.shields.io/badge/Home%20Assistant-custom%20integration-41BDF5?logo=homeassistant&logoColor=white"></a>
  <img alt="Trail camera" src="https://img.shields.io/badge/trail%20camera-LTE-green">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12%2B-blue?logo=python&logoColor=white">
  <a href="https://github.com/kyvaith/Suntek-HA"><img alt="GitHub repo" src="https://img.shields.io/badge/GitHub-kyvaith%2FSuntek--HA-181717?logo=github"></a>
</p>

A Home Assistant custom integration for Suntek LTE trail cameras used for outdoor monitoring, wildlife observation, remote plots, feeders, and forest camera setups.

## Features

- Checks whether the camera is online.
- Wakes the camera through the Suntek cloud API.
- Adds a Home Assistant wake-up button.
- Provides the `suntek_lte_camera.wakeup` service.
- Creates a camera entity that can use an RTSP, HLS, MJPEG, or local P2P bridge URL.

## Installation

Copy this directory:

```text
custom_components/suntek_lte_camera
```

to your Home Assistant config directory:

```text
config/custom_components/suntek_lte_camera
```

Restart Home Assistant, then add the `Suntek LTE Camera` integration from Settings.

## Configuration

The camera `IMEI / device ID` is required. You can optionally provide the cloud password, Suntek server URL, and a stream URL template.

Default server:

```text
https://depro.car-dv.com/4gcardv
```

Example stream template:

```text
rtsp://192.0.2.10:8554/{device_id}
```

Available template variables:

```text
{device_id}
{imei}
{password}
{server_addr}
{av_server_addr}
```

## Live View Notes

The SuntekCam mobile app uses a proprietary P2P protocol for the actual live video feed. This integration handles the cloud status API, wake-up command, and standard stream handoff. App-equivalent live view requires an RTSP/HLS/MJPEG URL from the camera or a local P2P bridge.
