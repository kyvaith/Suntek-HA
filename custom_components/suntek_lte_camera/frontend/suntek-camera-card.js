class SuntekCameraCard extends HTMLElement {
  static getStubConfig(hass) {
    const camera = Object.keys(hass.states).find((entityId) =>
      entityId.startsWith("camera.")
    );
    const online = Object.keys(hass.states).find(
      (entityId) =>
        entityId.startsWith("binary_sensor.") &&
        entityId.toLowerCase().includes("online")
    );
    const lastWakeup = Object.keys(hass.states).find(
      (entityId) =>
        entityId.startsWith("sensor.") &&
        entityId.toLowerCase().includes("last_wakeup")
    );
    return {
      entity: camera,
      online_entity: online,
      last_wakeup_entity: lastWakeup,
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
          name: "online_entity",
          selector: { entity: { domain: "binary_sensor" } },
        },
        {
          name: "last_wakeup_entity",
          selector: { entity: { domain: "sensor" } },
        },
      ],
    };
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("Suntek Camera Card requires a camera entity");
    }
    this._config = config;
    this._busy = false;
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
    if (this._busy) {
      return;
    }

    this._busy = true;
    this._error = "";
    this._render();

    try {
      await this._hass.callService("suntek_lte_camera", "wakeup", {});
      await this._refreshEntities();
    } catch (err) {
      this._error = err?.message || "Wake-up failed";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  async _refreshEntities() {
    const entities = [
      this._config.entity,
      this._config.online_entity,
      this._config.last_wakeup_entity,
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
    const online = this._config.online_entity
      ? this._hass.states[this._config.online_entity]
      : undefined;
    const lastWakeup = this._config.last_wakeup_entity
      ? this._hass.states[this._config.last_wakeup_entity]
      : undefined;
    const onlineText = online ? online.state : "unknown";
    const onlineClass = onlineText === "on" ? "online" : "offline";
    const wakeText = lastWakeup ? lastWakeup.state : "never";
    const imageUrl = this._cameraImageUrl(camera);
    const title =
      this._config.name ||
      camera?.attributes?.friendly_name ||
      "Suntek LTE Camera";

    this.innerHTML = `
      <ha-card>
        <div class="preview">
          ${
            imageUrl
              ? `<img src="${imageUrl}" alt="${this._escape(title)}">`
              : `<div class="empty">Camera preview unavailable</div>`
          }
          <div class="shade"></div>
          <div class="headline">
            <div class="title">${this._escape(title)}</div>
            <div class="meta">
              <span class="dot ${onlineClass}"></span>
              ${this._escape(onlineText)}
            </div>
          </div>
        </div>
        <div class="actions">
          <button class="wake" type="button" ${this._busy ? "disabled" : ""}>
            <ha-icon icon="mdi:power"></ha-icon>
            <span>${this._busy ? "Waking..." : "Wake up"}</span>
          </button>
          <div class="last">
            <span>Last wake-up</span>
            <strong>${this._escape(wakeText)}</strong>
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
          height: 46%;
          background: linear-gradient(transparent, rgba(0, 0, 0, 0.62));
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
          background: #b0b0b0;
        }

        .dot.online {
          background: #39d353;
        }

        .dot.offline {
          background: #ff6b6b;
        }

        .actions {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 12px;
          align-items: center;
          padding: 12px;
        }

        .wake {
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

        .wake[disabled] {
          opacity: 0.65;
          cursor: progress;
        }

        .wake ha-icon {
          --mdc-icon-size: 20px;
        }

        .last {
          color: var(--secondary-text-color);
          font-size: 12px;
          line-height: 1.2;
          text-align: right;
        }

        .last strong {
          display: block;
          color: var(--primary-text-color);
          font-size: 13px;
          margin-top: 2px;
        }

        .error {
          padding: 0 12px 12px;
          color: var(--error-color);
          font-size: 13px;
        }
      </style>
    `;

    this.querySelector(".wake")?.addEventListener("click", () => this._wakeCamera());
  }

  _cameraImageUrl(camera) {
    if (!camera) {
      return "";
    }

    const token = camera.attributes?.access_token;
    const entityId = encodeURIComponent(this._config.entity);
    const cacheBust = Date.now();
    if (token) {
      return `/api/camera_proxy/${entityId}?token=${token}&t=${cacheBust}`;
    }
    return `/api/camera_proxy/${entityId}?t=${cacheBust}`;
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
  description: "Trail camera preview with online status and wake-up action.",
  preview: true,
});
