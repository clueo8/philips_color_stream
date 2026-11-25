# Philips ColorStream+ for Home Assistant

Custom Home Assistant integration for **Philips ColorStream+** (`DoubleColor`) Bluetooth Christmas lights powered by the Telink BLE Mesh chipset.

Compatible with **HACS** as a custom integration repository.

---

## Supported Hardware

- **Philips ColorStream+ / DoubleColor**
  - Chipset: **Telink Semiconductor** BLE Mesh (`0x0211`)
  - Bluetooth local names: `DoubleColor*`, `BiColor*`
  - Protocol: Telink BLE Mesh authenticated protocol + Willis Link Technology (`WLT`) commands
  - Features:
    - **Instant Power On / Off**
    - **Brightness (0–100%)**
    - **8 Built-in Lighting Effects**
    - **Independent Strand Control (Unicast)**: Control each strand separately with different colors, effects, and states.
    - **Synchronized "All Strands" Master Entity (Broadcast)**: Hardware mesh broadcast keeping fading and flashing animations in 100% lockstep sync across all strands.

---

## Supported Effects

1. **Steady White**
2. **Steady Multi**
3. **Fade White**
4. **Fade Multi**
5. **Flash White**
6. **Flash Multi**
7. **Fade Between White and Multi**
8. **Flash Between White and Multi**

---

## Installation via HACS (Custom Repository)

1. In Home Assistant, open **HACS** → **Integrations**.
2. Click the three dots menu (**⋮**) in the top right corner and select **Custom repositories**.
3. Enter repository URL:
   `https://github.com/clueo8/philips_color_stream`
4. Set the Type to **Integration** and click **Add**.
5. Find **Philips Color Stream**, click **Download**, and restart Home Assistant.

---

## Configuration & Setup

1. Ensure your Home Assistant Bluetooth adapter or **ESPHome Bluetooth Proxies** are active within range of the lights.
2. The light strands will be automatically discovered under **Settings → Devices & Services**.
3. Click **Configure** on each discovered strand to add it to Home Assistant.

### Independent vs. Group Control

- **Individual Strand Entities**: Each strand entity communicates via unicast. You can turn individual strands on or off, or set one section of your display to *Steady White* while another runs *Steady Multi*.
- **"All Strands" Master Entity**: Broadcasts directly across the 2.4 GHz hardware RF mesh. Use this master switch when you want to control everything together or run dynamic effects (*Fade Multi*, *Flash White*, etc.) in perfect hardware sync.
- **Customizable Options**: Click **Configure** on any strand's device card to toggle or move the *All Strands* master broadcast entity.

---

## Standalone CLI Test Tool

A standalone CLI test script is included at `test_doublecolor.py`:

```bash
# Verify internal cryptographic test vectors against HCI packet captures
python3 test_doublecolor.py test-vectors

# Power on
python3 test_doublecolor.py --mac 57:4c:42:01:c9:5a on

# Set brightness to 50%
python3 test_doublecolor.py --mac 57:4c:42:01:c9:5a brightness 50

# Set effect mode
python3 test_doublecolor.py --mac 57:4c:42:01:c9:5a mode "steady_multi"
python3 test_doublecolor.py --mac 57:4c:42:01:c9:5a mode "fade_multi"

# Power off
python3 test_doublecolor.py --mac 57:4c:42:01:c9:5a off
```
