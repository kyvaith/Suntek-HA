class SuntekCameraCard extends HTMLElement {
  static getStubConfig(hass) {
    const findEntity = (domain, needles) =>
      Object.keys(hass.states).find((entityId) => {
        if (!entityId.startsWith(`${domain}.`)) {
          return false;
        }
        const state = hass.states[entityId];
        const haystack = `${entityId} ${state?.attributes?.friendly_name || ""}`
          .toLowerCase()
          .replaceAll(" ", "_");
        return needles.some((needle) => haystack.includes(needle));
      });

    return {
      entity: findEntity("camera", ["suntek"]) || findEntity("camera", ["camera"]),
      cloud_entity: findEntity("binary_sensor", [
        "cloud_connection",
        "online",
        "suntek",
      ]),
      signal_entity: findEntity("sensor", ["signal"]),
      battery_entity: findEntity("sensor", ["battery"]),
      sd_entity: findEntity("sensor", ["sd_storage"]),
      temperature_entity: findEntity("sensor", ["temperature"]),
      last_wakeup_entity: findEntity("sensor", ["last_wakeup"]),
      last_media_sync_entity: findEntity("sensor", ["last_media_sync"]),
      sync_button_entity: findEntity("button", ["sync_cloud_media"]),
    };
  }

  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { domain: "camera" } },
        },
        {
          name: "cloud_entity",
          selector: { entity: { domain: "binary_sensor" } },
        },
        {
          name: "signal_entity",
          selector: { entity: { domain: "sensor" } },
        },
        {
          name: "battery_entity",
          selector: { entity: { domain: "sensor" } },
        },
        {
          name: "sd_entity",
          selector: { entity: { domain: "sensor" } },
        },
        {
          name: "temperature_entity",
          selector: { entity: { domain: "sensor" } },
        },
        {
          name: "last_wakeup_entity",
          selector: { entity: { domain: "sensor" } },
        },
        {
          name: "last_media_sync_entity",
          selector: { entity: { domain: "sensor" } },
        },
        {
          name: "sync_button_entity",
          selector: { entity: { domain: "button" } },
        },
      ],
    };
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("Suntek Camera Card requires a camera entity");
    }
    this._config = config;
    this._wakeBusy = false;
    this._syncBusy = false;
    this._error = "";
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 4;
  }

  getGridOptions() {
    return {
      columns: 6,
      rows: 4,
      min_columns: 3,
      min_rows: 3,
    };
  }

  async _wakeCamera() {
    if (this._wakeBusy) {
      return;
    }

    this._wakeBusy = true;
    this._error = "";
    this._render();

    try {
      await this._hass.callService("suntek_lte_camera", "wakeup", {});
      await this._refreshEntities();
    } catch (err) {
      this._error = err?.message || "Wake-up failed";
    } finally {
      this._wakeBusy = false;
      this._render();
    }
  }

  async _syncMedia() {
    if (this._syncBusy) {
      return;
    }

    this._syncBusy = true;
    this._error = "";
    this._render();

    try {
      const buttonEntity = this._config.sync_button_entity;
      if (buttonEntity) {
        await this._hass.callService("button", "press", {
          entity_id: buttonEntity,
        });
      } else {
        await this._hass.callService("suntek_lte_camera", "sync_cloud_media", {});
      }
      await this._refreshEntities();
    } catch (err) {
      this._error = err?.message || "Cloud media sync failed";
    } finally {
      this._syncBusy = false;
      this._render();
    }
  }

  async _refreshEntities() {
    const entities = [
      this._config.entity,
      this._config.cloud_entity || this._config.online_entity,
      this._config.signal_entity,
      this._config.battery_entity,
      this._config.sd_entity,
      this._config.temperature_entity,
      this._config.last_wakeup_entity,
      this._config.last_media_sync_entity,
    ].filter(Boolean);

    await Promise.all(
      entities.map((entityId) =>
        this._hass.callService("homeassistant", "update_entity", {
          entity_id: entityId,
        })
      )
    );
  }

  _render() {
    if (!this._hass || !this._config) {
      return;
    }

    const camera = this._hass.states[this._config.entity];
    const cloud = this._entityState("cloud_entity", "online_entity");
    const lastWakeup = this._entityState("last_wakeup_entity");
    const lastSync = this._entityState("last_media_sync_entity");
    const cloudText = cloud ? cloud.state : "unknown";
    const cloudClass = cloudText === "on" ? "online" : "offline";
    const streamUrl = this._cameraStreamUrl(camera);
    const title =
      this._config.name ||
      camera?.attributes?.friendly_name ||
      "Suntek LTE Camera";
    const metrics = this._metrics();

    this.innerHTML = `
      <ha-card>
        <div class="preview">
          ${
            streamUrl
              ? `<img src="${streamUrl}" alt="${this._escape(title)}">`
              : `<div class="empty">Camera preview unavailable</div>`
          }
          <div class="shade"></div>
          <div class="headline">
            <div class="title">${this._escape(title)}</div>
            <div class="meta">
              <span class="dot ${cloudClass}"></span>
              <span>Cloud ${this._escape(cloudText)}</span>
            </div>
          </div>
        </div>
        ${
          metrics.length
            ? `<div class="metrics">${metrics
                .map(
                  (item) => `
                    <div class="metric">
                      <ha-icon icon="${item.icon}"></ha-icon>
                      <span>${this._escape(item.label)}</span>
                      <strong>${this._escape(item.value)}</strong>
                    </div>
                  `
                )
                .join("")}</div>`
            : ""
        }
        <div class="actions">
          <button class="wake" type="button" ${this._wakeBusy ? "disabled" : ""}>
            <ha-icon icon="mdi:power"></ha-icon>
            <span>${this._wakeBusy ? "Waking..." : "Wake up"}</span>
          </button>
          <button class="sync" type="button" ${this._syncBusy ? "disabled" : ""}>
            <ha-icon icon="mdi:cloud-download-outline"></ha-icon>
            <span>${this._syncBusy ? "Syncing..." : "Sync media"}</span>
          </button>
        </div>
        <div class="footer">
          <div>
            <span>Last wake-up</span>
            <strong>${this._escape(lastWakeup?.state || "never")}</strong>
          </div>
          <div>
            <span>Last media sync</span>
            <strong>${this._escape(lastSync?.state || "never")}</strong>
          </div>
        </div>
        ${this._error ? `<div class="error">${this._escape(this._error)}</div>` : ""}
      </ha-card>
      <style>
        ha-card {
          overflow: hidden;
          border-radius: var(--ha-card-border-radius, 8px);
        }

        .preview {
          position: relative;
          aspect-ratio: 16 / 10;
          background: var(--secondary-background-color);
          overflow: hidden;
        }

        .preview img {
          width: 100%;
          height: 100%;
          display: block;
          object-fit: cover;
        }

        .empty {
          height: 100%;
          display: grid;
          place-items: center;
          color: var(--secondary-text-color);
          font-size: 14px;
        }

        .shade {
          position: absolute;
          inset: auto 0 0;
          height: 48%;
          background: linear-gradient(transparent, rgba(0, 0, 0, 0.66));
        }

        .headline {
          position: absolute;
          left: 16px;
          right: 16px;
          bottom: 14px;
          color: white;
          display: flex;
          align-items: end;
          justify-content: space-between;
          gap: 12px;
        }

        .title {
          font-size: 18px;
          font-weight: 600;
          min-width: 0;
          overflow-wrap: anywhere;
        }

        .meta {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          font-size: 13px;
          text-transform: uppercase;
          white-space: nowrap;
        }

        .dot {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: #9aa0a6;
        }

        .dot.online {
          background: #34a853;
        }

        .dot.offline {
          background: #ea4335;
        }

        .metrics {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 1px;
          background: var(--divider-color);
        }

        .metric {
          min-width: 0;
          display: grid;
          grid-template-columns: 22px minmax(0, 1fr) auto;
          align-items: center;
          gap: 8px;
          padding: 10px 12px;
          background: var(--card-background-color);
          font-size: 13px;
        }

        .metric ha-icon {
          --mdc-icon-size: 19px;
          color: var(--secondary-text-color);
        }

        .metric span {
          color: var(--secondary-text-color);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .metric strong {
          color: var(--primary-text-color);
          font-weight: 600;
          white-space: nowrap;
        }

        .actions {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 10px;
          padding: 12px;
        }

        .actions button {
          min-width: 0;
          min-height: 40px;
          border: 0;
          border-radius: 8px;
          background: var(--primary-color);
          color: var(--text-primary-color);
          font: inherit;
          font-weight: 600;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          cursor: pointer;
        }

        .actions button[disabled] {
          opacity: 0.65;
          cursor: progress;
        }

        .actions ha-icon {
          --mdc-icon-size: 20px;
        }

        .footer {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 12px;
          padding: 0 12px 12px;
          color: var(--secondary-text-color);
          font-size: 12px;
          line-height: 1.2;
        }

        .footer strong {
          display: block;
          color: var(--primary-text-color);
          font-size: 13px;
          margin-top: 3px;
          overflow-wrap: anywhere;
        }

        .error {
          padding: 0 12px 12px;
          color: var(--error-color);
          font-size: 13px;
        }

        @media (max-width: 420px) {
          .headline,
          .actions,
          .footer {
            grid-template-columns: 1fr;
          }

          .headline {
            align-items: start;
            flex-direction: column;
          }

          .metrics {
            grid-template-columns: 1fr;
          }
        }
      </style>
    `;

    this.querySelector(".wake")?.addEventListener("click", () => this._wakeCamera());
    this.querySelector(".sync")?.addEventListener("click", () => this._syncMedia());
  }

  _metrics() {
    return [
      this._metric("signal_entity", "Signal", "mdi:signal"),
      this._metric("battery_entity", "Battery", "mdi:battery"),
      this._metric("sd_entity", "SD", "mdi:sd"),
      this._metric("temperature_entity", "Temp", "mdi:thermometer"),
    ].filter(Boolean);
  }

  _metric(configKey, label, icon) {
    const state = this._entityState(configKey);
    if (!state || state.state === "unknown" || state.state === "unavailable") {
      return undefined;
    }
    const unit = state.attributes?.unit_of_measurement || "";
    return {
      icon,
      label,
      value: `${state.state}${unit}`,
    };
  }

  _entityState(primaryKey, fallbackKey) {
    const entityId = this._config[primaryKey] || this._config[fallbackKey];
    return entityId ? this._hass.states[entityId] : undefined;
  }

  _cameraStreamUrl(camera) {
    if (!camera) {
      return "";
    }

    const token = camera.attributes?.access_token;
    const entityId = encodeURIComponent(this._config.entity);
    if (token) {
      return `/api/camera_proxy_stream/${entityId}?token=${token}`;
    }
    return `/api/camera_proxy_stream/${entityId}`;
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
}

customElements.define("suntek-camera-card", SuntekCameraCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "suntek-camera-card",
  name: "Suntek Camera",
  description: "Trail camera preview with cloud status, camera metrics, and media sync.",
  preview: true,
});
