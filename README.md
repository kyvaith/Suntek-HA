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

Integracja Home Assistant dla kamer leśnych Suntek LTE, czyli trail camera używanych do monitoringu terenu, działki, lasu albo karmiska.

## Funkcje

- sprawdzanie, czy kamera jest online,
- wybudzanie kamery przez chmurę Suntek,
- przycisk `Wybudź` w Home Assistant,
- usługa `suntek_lte_camera.wakeup`,
- encja kamery z obsługą URL RTSP/HLS/MJPEG albo lokalnego bridge'a P2P.

## Instalacja

Skopiuj katalog:

```text
custom_components/suntek_lte_camera
```

do:

```text
config/custom_components/suntek_lte_camera
```

Następnie zrestartuj Home Assistant i dodaj integrację `Suntek LTE Camera` z poziomu ustawień.

## Konfiguracja

Wymagane jest `IMEI / ID urządzenia`. Opcjonalnie możesz podać hasło cloud, adres serwera Suntek oraz szablon URL streamu.

Domyślny serwer:

```text
https://depro.car-dv.com/4gcardv
```

Przykład szablonu streamu:

```text
rtsp://192.0.2.10:8554/{device_id}
```

Dostępne zmienne w szablonach:

```text
{device_id}
{imei}
{password}
{server_addr}
{av_server_addr}
```

## Uwaga o live view

Aplikacja SuntekCam używa zamkniętego protokołu P2P do właściwego obrazu na żywo. Ta integracja obsługuje część chmurową, wybudzanie oraz podłączenie standardowego streamu. Pełny live view jak w aplikacji wymaga URL RTSP/HLS/MJPEG z kamery albo lokalnego bridge'a P2P.
