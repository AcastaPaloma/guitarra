# Handoff to Claude: Feetech / Waveshare USB driver diagnosis on a personal computer

## Task and permission boundary

Help the operator download, verify, and install the official WCH USB serial driver on **their own computer**, then perform a controlled, non-motion diagnostic comparison.

The previous computer blocked the driver application. **Do not bypass that computer's security policy.** Do not disable SIP, Gatekeeper, endpoint protection, or driver-signing checks; do not remove quarantine attributes to force execution. Ordinary, operator-approved Driver Extension activation in System Settings is appropriate on an authorized personal computer. If installation is policy-blocked there too, stop and report it.

First confirm the destination OS, that the operator controls the computer, and approval for driver installation. The commands below are for **macOS**. For Windows or Linux, use the manufacturer's corresponding procedure instead of running these commands or guessing at a driver.

**Keep the adapter USB-only during installation and initial testing: no servo cable and no external 12 V supply.** Do not disconnect power from a servo holding a gripper/tool to achieve this; ask the operator to prepare a safe, unloaded bench setup first.

## What is known — do not restart the investigation from assumptions

- Motor: **FeeTech STS3215-12V**, a three-wire half-duplex TTL bus servo.
- Original photographed adapter: **Waveshare Bus Servo Adapter (A), V1.1**.
- Its pictured servo connection was white → D, red → V, black → G. Both selector jumpers appeared to be in **B / USB–SERVO**.
- Both white D/V/G sockets on that design share the bus and power rail. Two sockets do not double power capacity.
- WCH USB interface: **VID `1A86`, PID `55D3`**, CH343 family, described as `USB Single Serial`.
- Previous host: Apple Silicon, **macOS 27.0**. The adapter was bound to **AppleUSBCDCCompositeDevice / AppleUSBACMControl / AppleUSBACMData**.
- No checksum-valid motor identification has been obtained. A red motor LED and a USB serial port are not proof of servo communication.
- Only Feetech **PING (`0x01`) and READ (`0x02`)** instructions were sent. No movement, torque changes, motor ID/baud writes, calibration, or reset commands were sent.
- Three distinct **adapter USB serial numbers** appeared. These are NOT servo IDs:

| Adapter USB serial | Observations |
| --- | --- |
| `5B79016319` | Initially enumerated; motor-connected scans received zero bytes across IDs 0–253 and eight standard baud rates. |
| `5AB0181168` | Returned repeatable malformed data both with a motor connected and with only USB connected. This is the main driver-comparison candidate. |
| `5B8E113663` | USB-only test was silent for the same 52 requests. A subsequent motor scan had no replies at the completed rates and was interrupted before the last rate finished. Silence alone does not prove a healthy adapter. |

### The useful raw-byte evidence

For adapter `5AB0181168`, at 115,200 baud:

```text
PING ID 1 sent:          FF FF 01 02 01 FB
Received with motor:    00 00 7F BF 09
Received with USB only: 00 00 7F BF 09

READ model ID 1 sent:   FF FF 01 04 02 03 02 F3
Received:              00 00 7F DF F9 FB 19
```

At 1,000,000 baud, the corresponding ping returned `80 80 03`.

- All **52 paired requests** returned byte-for-byte identical data with and without the motor/cable/external supply attached.
- Across 39 captures at 19,200, 115,200, and 500,000 baud, the bytes exactly matched an **offline prediction of the transmitted UART waveform decoded with inverted polarity**. That is a diagnostic hypothesis, not a physical voltage measurement.
- No bytes arrived during the idle capture periods.
- The installed Feetech SDK, raw pySerial, and a direct POSIX test bypassing both libraries received the same malformed bytes.
- Host settings were checked: 8N1, echo off, canonical mode off, flow control off, no high-bit stripping or output translation.
- **All three software tests still used Apple's same underlying USB driver. They did not rule out a driver/USB compatibility problem.**

Interpretation: those bytes are not motor replies. Their source does not require the motor or servo cable. Adapter circuitry/configuration and the host USB/driver path remain candidates. Do not call the motor healthy, the cable faulty, or a board fried based on this evidence alone. Do not "fix" received bytes and present the recovered outgoing request as motor telemetry.

## Official software already researched

Vendor documentation:

- WCH macOS driver repository and installation guide: <https://github.com/WCHSoftGroup/ch34xser_macos>
- WCH's CDC compatibility explanation: <https://github.com/WCHSoftGroup/ch343ser_linux>
- Waveshare adapter documentation: <https://www.waveshare.com/wiki/Bus_Servo_Adapter_%28A%29>

WCH documents CH343 support in both standard CDC drivers and its vendor driver. **Using Apple's driver is not automatically an error.** Installing WCH's driver is a controlled comparison, not a guaranteed fix.

The reviewed vendor archive was commit:

```text
09629694b207cdce66861b6fe821b68993507be9
```

Reviewed release contents:

- App: `CH34xVCPDriver.app`, **version 2.1, build 7**.
- Bundle identifier: `cn.wch.CH34xVCPDriver`.
- Apple Silicon `arm64` and Intel `x86_64` binaries, including a DriverKit extension.
- The extension explicitly matches USB **`1A86:55D3`**.
- Signing team: **`5JZGQTGU4W` — Nanjing Qinheng Microelectronics Co., Ltd.**
- On the previous host, `codesign --verify --deep --strict` passed and Gatekeeper assessment returned **accepted / Notarized Developer ID** for the app inside the DMG.
- This does not establish successful operation on macOS 27 or any new destination host.

The `.pkg` wrapper declares an Intel host architecture despite containing universal binaries. Prefer the vendor's **DMG/app installation route** for Apple Silicon rather than introducing a Rosetta dependency or installing legacy kexts unnecessarily.

### State left on the previous computer

The verified app was copied to `/Applications/CH34xVCPDriver.app` and launch was requested. The operator reported it was blocked. WCH's extension had **not** appeared as activated in the latest check, and the serial device still used Apple's driver.

No security settings were weakened. No vendor firmware was flashed. Do not describe that attempt as a successful driver switch or successful motor test. Do not attempt further changes on that computer as part of this handoff.

## Download on the destination Mac

Use a dedicated folder. Download from the pinned official vendor commit, not a third-party driver mirror:

```bash
WORK="$HOME/Downloads/feetech-adapter-check"
mkdir -p "$WORK"
cd "$WORK"

curl --proto '=https' --tlsv1.2 --fail --location \
  'https://raw.githubusercontent.com/WCHSoftGroup/ch34xser_macos/09629694b207cdce66861b6fe821b68993507be9/CH34xVCPDriver.dmg' \
  --output CH34xVCPDriver-2.1.dmg

printf '%s  %s\n' \
  '8fbaa392ab06a1f942f996ec12ab1bf9c5567755ebad3c9db591641aa9b787b8' \
  'CH34xVCPDriver-2.1.dmg' | shasum -a 256 -c -

hdiutil verify CH34xVCPDriver-2.1.dmg
```

**Stop on any failed download or checksum mismatch.** A different future release can be reviewed separately; do not silently substitute it while claiming this pinned version was tested. Disk-image checksum verification is not a substitute for app-signature verification.

## Controlled installation and comparison

Do these stages deliberately, not as one unattended batch.

1. Confirm **USB-only, no servo cable, no external 12 V**. Identify the actual connected adapter; prefer `5AB0181168` for the inverted-echo comparison. Keep the same board, USB cable, and computer port before and after the driver change.
2. If possible, capture a fresh pre-installation baseline on this destination Mac using the probe below. Changing computers is already a variable; do not claim a driver caused improvement without a same-host comparison.
3. Mount the DMG read-only. Determine the actual mount path rather than assuming one:

   ```bash
   hdiutil attach -readonly -nobrowse "$HOME/Downloads/feetech-adapter-check/CH34xVCPDriver-2.1.dmg"
   ```

4. Before launching, verify the mounted app. Substitute its actual path for `APP`:

   ```bash
   APP="/Volumes/CH34xVCPDriver/CH34xVCPDriver.app"
   codesign --verify --deep --strict --verbose=2 "$APP"
   codesign -d --verbose=4 "$APP"
   spctl --assess --type execute --verbose=2 "$APP"
   ```

   Check the signing team above and notarization acceptance. Stop on failure; do not disable checks. If an existing WCH app/driver is present, inspect its version and plan any replacement instead of overwriting it blindly.
5. With approval, use the vendor's documented app installation: copy the app into `/Applications`, open it, and click **Install**. The operator must approve any legitimate Driver Extension authorization prompt in System Settings. Do not automate password entry or try to bypass a policy block.
6. Reconnect **USB only** when requested. Verify BOTH extension activation and which driver actually owns this adapter:

   ```bash
   systemextensionsctl list
   ls /dev/cu.*
   ioreg -r -c IOUSBHostDevice -l -w0 | grep -E 'USB Single Serial|CH34|AppleUSBACM|IOCalloutDevice|IOTTY'
   ```

   WCH's documentation describes a `wchusbserial` device name, but discover the actual port. An installed app or enabled extension is not proof this particular device has rebound to it. Do not remove Apple's system driver.
7. Repeat the exact USB-only probe and compare raw bytes. Report whether the inverted echo remains, disappears, changes, or the device no longer enumerates. A silent empty adapter is **not** yet a successful motor connection.
8. Only after reviewing that result and obtaining operator readiness, plan a **single unloaded motor** test with appropriate power. Change servo wiring only with both supplies disconnected. Use only PING/READ, enumerate rather than guessing its ID, and require a checksum-valid model response. STS3215 normally reports model number **777**. Do not run the normal robot connection path to "test" it.

## Optional short USB-only probe (macOS, no robot library)

This probe is intentionally **not a motor sweep**. It sends only fixed PING/model-READ requests and prints raw bytes. It does not change servo registers or report motor health.

If needed, with approval create a separate Python environment under the work folder, not inside another project's environment:

```bash
cd "$HOME/Downloads/feetech-adapter-check"
python3 -m venv .venv
.venv/bin/python -m pip install 'pyserial==3.5'
```

Save the following as `adapter_usb_only_probe.py` in that folder. Pass the discovered port explicitly; do not copy the previous computer's port name blindly. No other program may own the port.

```python
import argparse
import subprocess
import sys
import time

import serial
from serial.tools import list_ports

ap = argparse.ArgumentParser()
ap.add_argument('--port', required=True)
ap.add_argument('--adapter-only', action='store_true')
args = ap.parse_args()
if sys.platform != 'darwin':
    raise SystemExit('This ownership-check procedure is for macOS; review before adapting.')
if not args.adapter_only:
    raise SystemExit('Confirm USB-only: no servo cable and no external 12 V; then pass --adapter-only.')
ports = {p.device: p for p in list_ports.comports()}
p = ports.get(args.port)
if p is None or (p.vid, p.pid) != (0x1A86, 0x55D3):
    raise SystemExit('Expected WCH device not found at that port; inspect instead of guessing.')
print('Adapter:', p.device, 'USB serial:', p.serial_number)
owners = subprocess.run(
    ['lsof', args.port, args.port.replace('/dev/cu.', '/dev/tty.')],
    capture_output=True, text=True,
)
if owners.returncode != 1 or owners.stdout.strip() or owners.stderr.strip():
    raise SystemExit('Port ownership check not clear; close other serial programs first.')

for baud in (1_000_000, 115_200):
    with serial.Serial(
        args.port, baud, timeout=0.002, write_timeout=0.5, exclusive=True,
        bytesize=8, parity='N', stopbits=1,
        xonxoff=False, rtscts=False, dsrdtr=False,
    ) as s:
        time.sleep(0.05)
        for ident in (1, 12, 253):
            for instruction, params in ((1, ()), (2, (3, 2))):
                # Only PING or a two-byte model-number READ. No register writes.
                assert instruction in (1, 2)
                body = bytes((ident, len(params) + 2, instruction, *params))
                tx = b'\xff\xff' + body + bytes(((~sum(body)) & 255,))
                s.reset_input_buffer()
                assert s.write(tx) == len(tx)
                deadline = time.monotonic() + 0.25
                rx = bytearray()
                while time.monotonic() < deadline:
                    rx.extend(s.read(min(4096, max(1, s.in_waiting))))
                print({'baud': baud, 'id': ident, 'tx': tx.hex(' '),
                       'rx': rx.hex(' ')}, flush=True)
print('Serial port closed. Only PING/model-READ requests were sent.')
```

Example invocation — replace the port placeholder:

```bash
.venv/bin/python adapter_usb_only_probe.py \
  --port /dev/cu.REPLACE_WITH_DISCOVERED_PORT --adapter-only
```

Save separate before/after outputs. Never describe a response at every requested ID as many detected motors: it can be local echo, as seen here.

## Non-negotiable hardware boundaries

- Do not run motion, all-motor torque-off, homing, firmware flashing, factory reset, ID/baud writes, or calibration as diagnosis.
- Do not call the guitar project's normal `connect()` / disconnect cleanup as a neutral test; those paths can configure motors and affect holding torque.
- Grippers must remain clamped during normal operation. A previous guitar gripper reached **75 C**. Last recorded live torque limit was **110**, while the plugin default remained **180**. Do not reconnect through that default or raise torque. That motor has not been qualified for sustained holding.
- Respect thermal/electrical faults. Do not disable protection to preserve a grip. No unattended rehearsal, sweeps, or two-arm load tests.
- Sharing an adapter's two servo sockets shares both data and power. Unique IDs, one bus owner, and a verified combined current budget are required. Do not parallel power supplies through the shared positive rail. This driver task is not approval to power two complete arms.

## Report back

Provide: destination OS/architecture; adapter USB serial; driver/app version and signature result; driver actually bound before and after; port names; exact raw-byte comparison; any block/error; and whether a later explicitly approved motor test returned a checksum-valid ID/model. Keep host/driver success separate from motor communication and physical readiness.

Do not claim the driver fixed the problem merely because installation succeeded. Do not collect/upload camera, microphone, credentials, or unrelated machine data.
