# cc_pid

A supervisory PID fan controller plugin for [CoolerControl](https://gitlab.com/coolercontrol/coolercontrol).
It reads a temperature sensor through the `coolercontrold` REST API, computes a fan duty
with a PID loop (deadband, anti-windup, filtered derivative, safety override), and writes it
to a `Fixed` profile.

## Install

```bash
git clone https://github.com/<you>/cc_pid.git
cd cc_pid
sudo ./install.sh
```

Re-running the script updates the plugin and keeps your existing `config.json`.
Options: `--no-restart`, `--uninstall`, `--purge`.

Requirements: CoolerControl with plugin support, Python 3, `requests`
(installed automatically via your package manager).

## API token

Create an access token in CoolerControl (Access Protection → Access Tokens) and put it in
`<plugin dir>/token` (default `/etc/cc_pid/token`, mode 600).
The installer creates the empty file and never overwrites it. The `COOLERCONTROL_TOKEN`
environment variable also works and takes priority. The token is never stored in
`manifest.toml`.

The plugin runs as `cc-plugin-user`, so the installer gives that user ownership of the
scripts, `ui/index.html`, `config.json` and `token`. The plugin directory, `ui/` and `manifest.toml` stay root-owned. If your plugin runs as a
different user, run `sudo PLUGIN_USER=<user> ./install.sh`.

## Configure

Open the plugin page in the CoolerControl UI, add a control, pick a temperature source and a
`Fixed` profile, set the PID values, and save. See `config.example.json` for the schema.

| Setting | Meaning |
|---|---|
| `target_temp` | Temperature the loop aims for (°C) |
| `deadband` / `deadband_offset` | Zone around target where error is treated as 0 |
| `min_duty` / `max_duty` | Output clamp (%) |
| `target_duty` | Baseline duty added to the PID output |
| `kp` / `ki` / `kd` | Proportional, integral, derivative gains |

A hard safety override forces 100% duty at `critical_temp` (default 87 °C) until the
temperature drops `safety_margin` (default 5 °C) below it.

## Files

- `cc_pid.py`: control loop
- `models.py`: PID controller and CoolerControl client
- `ui/index.html`: plugin UI
- `manifest.toml`: CoolerControl plugin manifest
- `install.sh`: installer

## License

TBD
