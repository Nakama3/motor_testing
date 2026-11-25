# WiFi Heatmap

Walk around your house with a laptop and map your WiFi signal strength in 2D and 3D.

- Place the router on a top-down floor plan (multiple floors supported).
- Click where you're standing and press **Space** to take a sample. The app reads the
  real signal strength (RSSI, dBm) from your laptop's WiFi card and averages a few readings.
- See a 2D heatmap of each floor and a 3D point cloud of the whole house. Values between
  samples are estimated from a path-loss model (signal falls off with distance from the
  router and with each floor in between), corrected toward your nearby measurements.

## Run it

Needs Python 3.8+ (standard library only) and a browser with internet access
(three.js loads from a CDN).

```bash
cd wifi_heatmap
python3 server.py          # open http://localhost:8000
python3 server.py --demo   # simulated signal, to try it without walking around
```

Samples auto-save to `wifi_heatmap/project.json` (and to the browser). Use **Export JSON**
to keep a copy, or **Export CSV** for a spreadsheet.

### How the signal is read

Browsers can't read WiFi signal strength, so `server.py` asks the OS:

| OS | Method |
|---|---|
| Linux | `iw dev <iface> link`, then `/proc/net/wireless`, then `nmcli` |
| macOS | CoreWLAN (if `pip install pyobjc-framework-CoreWLAN`), then `airport`, then `system_profiler` (works, but takes a few seconds per reading) |
| Windows | `netsh wlan show interfaces` (uses `Rssi` on Windows 11, else converts `Signal %`) |

**Using a phone instead?** Run the server with `--host 0.0.0.0`, open
`http://<laptop-ip>:8000` on the phone, and type the dBm from a WiFi analyzer app into
**Manual dBm** for each spot.

## Walk mode (fastest way to cover the house)

Instead of one click per sample, sample continuously while you walk:

1. Click where you're standing, then press **W**.
2. Walk at a steady pace in a straight line. The laptop reads the signal about every 0.6 s.
3. At each corner or turn, click where you are now. The readings since the last point are
   spread evenly along that straight leg, based on when each one was taken.
4. Keep going leg by leg, then press **Esc** to stop. Readings after your last click are discarded.

On macOS, install CoreWLAN first (`pip install pyobjc-framework-CoreWLAN`). Without it each
reading takes a few seconds, so a walk only gets a handful of samples.

## Tips

- Set **Width / Depth** to your house's outer dimensions first, and optionally upload a
  floor plan image for each floor (it's stretched to fill width × depth).
- Hold the laptop at the same height for every sample (**Device height**).
- Sample on a grid of about 1.5–2 m (5–6 ft), plus every corner, the far rooms, and anywhere
  you actually use devices.
- Under **Map display**, set **Show → Below midpoint** to see only weak spots in 3D.
  The midpoint (default −67 dBm) is a common minimum for reliable video calls.

Rough guide: ≥ −50 excellent · −60 good · −67 fair · −75 weak · below that, poor.
