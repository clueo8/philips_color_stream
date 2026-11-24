# Philips Color Stream / DoubleColor for Home Assistant

Custom Home Assistant integration for **Philips ColorStream+** and **Philips Color Stream** Bluetooth Christmas lights.

Compatible with **HACS** as a custom integration repository.

---

## Supported Hardware

1. **Philips ColorStream+ / DoubleColor (Current Generation)**
   - Hardware: **Telink Semiconductor** BLE Mesh chip (`0x0211`)
   - Advertising names: `DoubleColor*`, `BiColor*`
   - Protocol: Telink legacy mesh encrypted protocol + Willis Link Technology (`WLT`) commands
   - Features: **Power On/Off**, **Brightness (0–100%)**, **10 Built-in Effects**, **Speed Control**

2. **Philips Color Stream (Legacy Generation)**
   - Advertising names: `GV_RGB_*`
   - Protocol: Direct unencrypted GATT `FFF0`/`FFF2`
   - Features: **Power On/Off**, **27 Built-in Effects**, **Speed Control**

---

## Installation via HACS (Custom Repository)

1. In Home Assistant, open **HACS** → **Integrations**.
2. Click the three dots menu (**⋮**) in the top right corner and select **Custom repositories**.
3. Enter your Gitea repository URL:
   `https://github.clue.giize.com/clue/philips_color_stream` (or your repository URL)
4. Set the Type to **Integration** and click **Add**.
5. Find **Philips Color Stream**, click **Download**, and restart Home Assistant.

---

## Configuration & Discovery

Once installed and Home Assistant has restarted:
1. Ensure your Bluetooth adapter or **ESPHome Bluetooth Proxies** are running within range of the lights.
2. The light strands will be automatically discovered under **Settings → Devices & Services**.
3. Click **Configure** on each strand to add them.

*Note: The lights can only maintain one active Bluetooth connection at a time. The integration automatically disconnects when idle so you can still use the mobile app when desired.*

---

## Supported Effects (DoubleColor)

- **Combo**
- **Steady White**
- **Fade White**
- **Steady Multi**
- **Fade Multi**
- **Fade Between**
- **Twinkle / Flash**
- **In Waves**
- **Slow Fade**
- **Gradient**

---

## Standalone Test Tool

A standalone CLI test script is included at `test_doublecolor.py`:

```bash
# Verify cryptographic test vectors
python3 test_doublecolor.py test-vectors

# Turn on
python3 test_doublecolor.py --mac 57:4c:42:01:c9:5a on

# Set brightness to 50%
python3 test_doublecolor.py --mac 57:4c:42:01:c9:5a brightness 50

# Set effect mode
python3 test_doublecolor.py --mac 57:4c:42:01:c9:5a mode twinkle

# Turn off
python3 test_doublecolor.py --mac 57:4c:42:01:c9:5a off
```
