# Philips ColorStream+ for Home Assistant

Custom Home Assistant integration for **Philips ColorStream+** (`DoubleColor`) Bluetooth Christmas lights powered by the Telink BLE Mesh chipset.

---

## Features

- **Instant Power On / Off**
- **Brightness Control (0–100%)**
- **8 Built-in Lighting Effects**:
  - Steady White
  - Steady Multi
  - Fade White
  - Fade Multi
  - Flash White
  - Flash Multi
  - Fade Between White and Multi
  - Flash Between White and Multi
- **Independent Strand Control (Unicast)**: Control each strand separately with different colors, effects, and states.
- **Synchronized "All Strands" Master Entity (Broadcast)**: Hardware mesh broadcast keeping fading and flashing animations in 100% lockstep sync across all strands.

---

## Configuration & Setup

1. Ensure your Home Assistant Bluetooth adapter or **ESPHome Bluetooth Proxies** are active within range of the lights.
2. The light strands will be automatically discovered under **Settings → Devices & Services**.
3. Click **Configure** on each discovered strand to add it to Home Assistant.

### Independent vs. Group Control

- **Individual Strand Entities**: Each strand entity communicates via unicast. You can turn individual strands on or off, or set one section of your display to *Steady White* while another runs *Steady Multi*.
- **"All Strands" Master Entity**: Broadcasts directly across the 2.4 GHz hardware RF mesh. Use this master switch when you want to control everything together or run dynamic effects (*Fade Multi*, *Flash White*, etc.) in perfect hardware sync.
- **Customizable Options**: Click **Configure** on any strand's device card to toggle or move the *All Strands* master broadcast entity.
