# Deployment

## Windows: setup window

1. Unzip the release to its final place, e.g. `C:\Program Files\PortraitQA\`. The service runs from there, and
   `config.json` and `logs\` are created next to the executables.
2. Run **`PortraitQA.exe`**. It asks for administrator rights, which installing a service needs.
3. Choose:
   - **Access:** *this computer only* (`127.0.0.1`: only programs on this machine can call it) or *network*
     (all interfaces). Network mode generates an API key, which is required, and offers to open the port in
     Windows Firewall.
   - **Port:** **Check** binds the port to see if it is free. If another program holds it, the window says so
     and offers the next free port. A port held by Portrait QA itself is accepted (reconfiguring).
4. **Install and start** saves `config.json`, installs the `PortraitQA` service (automatic start, restart after
   a crash or a failed start: 5 s, 5 s, then every 30 s), starts it, and waits until `/v1/health` answers.
   A failed start (invalid `config.json`, port taken by another program) is logged in `logs\portrait-qa.log`
   and in the Windows Application event log, and retried.
5. The **Endpoints** box lists the URLs with **Copy** buttons. **Open test page** opens `/` in the browser to
   try a photo.

Changing the port or the access mode later: open the window again and click **Apply and restart**.
**Uninstall** removes the service and the firewall rule, and keeps `config.json` and the logs.

## Windows: silent install

For scripted deployments, use the console executable from an administrator prompt:

```powershell
cd "C:\Program Files\PortraitQA"; .\portrait-qa.exe install --network --port 8080
```

It runs the same steps as the window and prints the URLs and the API key as JSON. Options: `--local`,
`--api-key <key>` (default: keep the current one, or generate one in network mode), `--no-firewall`.
`portrait-qa.exe status` prints the service state and the health answer (exit 1 if not answering).
`portrait-qa.exe uninstall` removes the service.

Exit codes: 0 ok, 2 error (busy port, missing key, not administrator...), with the reason on stderr.

## Linux

```bash
python3 -m venv /opt/portrait-qa && /opt/portrait-qa/bin/pip install .
/opt/portrait-qa/bin/portrait-qa --config /etc/portrait-qa/config.json serve
```

A systemd unit:

```ini
[Unit]
Description=Portrait QA
After=network-online.target

[Service]
ExecStart=/opt/portrait-qa/bin/portrait-qa --config /etc/portrait-qa/config.json serve
User=portrait-qa
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Logs go to `logs/portrait-qa.log` next to the config file and to the console (journald). Use
`serve --no-log-file` to log to the console only.

## Docker

```bash
docker build -t portrait-qa .
docker run -d --name portrait-qa -p 8080:8080 -v /etc/portrait-qa/config.json:/config/config.json:ro portrait-qa
```

Inside the container the API listens on all interfaces, so set `server.api_key` in the mounted config.

## config.json

All keys are optional. Unknown keys and wrong types are refused at startup, with the key named in the
message.

```json
{
  "server": {
    "host": "127.0.0.1",
    "port": 8080,
    "api_key": "",
    "max_concurrency": 0,
    "queue_timeout_seconds": 10,
    "cors_origins": []
  },
  "limits": { "max_upload_mb": 10, "max_megapixels": 50 },
  "detector": { "score_threshold": 0.6, "max_side": 640 },
  "quality": { "min_score": 60, "min_sharpness": 15, "min_brightness": 70, "max_brightness": 200 },
  "default_profile": "default",
  "profiles": {
    "terminal": { "width": 480, "height": 640, "max_kb": 100, "face_width_ratio": 0.5, "eye_line": 0.42,
                  "background": [255, 255, 255], "description": "Door terminal" }
  },
  "log_level": "info"
}
```

- `server.max_concurrency`: photos processed in parallel (0 = CPU cores). Extra requests wait up to
  `queue_timeout_seconds` and then get `503 BUSY`.
- `server.cors_origins`: web origins allowed to call the API from a browser.
- `quality`: every threshold in [quality.md](quality.md).
- `profiles`: extra output profiles (or overrides of the built-in ones). `background` is B, G, R, used when the
  photo has no room around the face. Check the target device's manual for its size and file limits; the
  built-in profiles are generic.

Location: `--config <path>`, else the `PORTRAIT_QA_CONFIG` environment variable, else `config.json` next to
the executable (Windows build) or in the current directory.

## Security notes

- Face photos are biometric personal data (LGPD art. 5, GDPR art. 9). The service keeps them in memory only
  for the request, never writes them to disk, and does not log them.
- In network mode the API key is required. It travels in plain HTTP, so use the service on a trusted network,
  or put it behind a reverse proxy with TLS (IIS ARR, nginx, Caddy) when traffic crosses untrusted networks.
- Uploads are limited in size while they are read (chunked bodies included) and in pixel count before decoding
  (from the file header), and only JPEG/PNG/BMP/WebP signatures are decoded.
