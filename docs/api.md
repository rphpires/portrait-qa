# API reference

Base URL: `http://<host>:<port>` (default port 8080). The interactive reference generated from the code is at
`/docs` on a running service.

## Authentication

When `server.api_key` is set (always in network mode), every endpoint except `/`, `/v1/health` and `/docs`
needs the key:

```
X-API-Key: <key>
```

`Authorization: Bearer <key>` is accepted too. Without it: `401 UNAUTHORIZED`.

## Sending the image

Every `POST` endpoint takes the image in any of these forms (JPEG, PNG, BMP or WebP, up to
`limits.max_upload_mb`, default 10 MB, and `limits.max_megapixels`, default 50):

| Content-Type | Body |
|---|---|
| `multipart/form-data` | a file field named `image` |
| `application/json` | `{"image_base64": "<base64>"}`; a `data:image/jpeg;base64,` prefix is accepted |
| `image/jpeg`, `image/png`, `application/octet-stream` | the raw bytes |

EXIF orientation (photos taken with a phone held upright) is applied before anything else.

## Endpoints

### `POST /v1/assess`

Quality report only. Always `200` when the image is readable, even with no face (`NO_FACE` in the issues).

### `POST /v1/process?profile=<name>&format=json|jpeg`

The usual call: the quality report, and the cropped portrait **only if the photo passes**. When it fails,
`crop` is `null` and the issues say why.

### `POST /v1/crop?profile=<name>&format=json|jpeg`

Crops whenever a face exists, even if the quality check fails (the report is still returned). No face:
`422 NO_FACE`.

`profile` defaults to `default_profile` in `config.json`. With `format=jpeg` the response body is the JPEG
itself and the verdict goes in headers:

```
X-Portrait-Passed: true
X-Portrait-Score: 89
X-Portrait-Issues: LOW_RESOLUTION,LOW_CONTRAST
```

(`process` with `format=jpeg` on a failed photo answers the JSON report instead, with the same headers.)

### `GET /v1/profiles`

```json
{ "default": "default",
  "profiles": [ { "name": "badge", "width": 300, "height": 400, "face_width_ratio": 0.5, "eye_line": 0.42,
                  "max_face_width_ratio": 0.7, "max_kb": 60, "jpeg_quality": 92,
                  "background": [255, 255, 255], "description": "..." } ] }
```

### `GET /v1/health`

```json
{ "status": "ok", "name": "Portrait QA", "version": "1.0.0", "uptime_seconds": 3600, "auth_required": true }
```

## Response

```json
{
  "passed": false,
  "score": 53,
  "faces": 1,
  "image_size": [1200, 1600],
  "issues": [
    { "code": "BLURRY", "severity": "error", "message": "The face is blurry or out of focus.",
      "value": 4.2, "limit": 15.0 }
  ],
  "face": {
    "box": [412, 380, 360, 440],
    "confidence": 0.91,
    "eye_distance_px": 142.3,
    "yaw_ratio": 0.04,
    "sharpness": 4.2,
    "brightness": 151.0,
    "contrast": 38.2,
    "overexposed_fraction": 0.0,
    "lighting_imbalance": 12.5
  },
  "crop": null,
  "elapsed_ms": 61.4
}
```

| Field | Meaning |
|---|---|
| `passed` | no `error` issue and `score >= quality.min_score` |
| `score` | 0-100: sharpness 30, exposure 25, pose 25, resolution 10, detection confidence 10 |
| `faces` | faces that count (small faces in the background are ignored) |
| `issues[]` | `code` (stable), `severity` (`error`/`warning`), English `message`, measured `value` and `limit` |
| `face` | measurements of the main face; `box` = `[x, y, width, height]` in the sent image |
| `crop` | `profile`, `width`, `height`, `bytes`, `image_base64`, `source_box` (crop area in the sent image), `padded` (background added because there was no room), `upscaled` (the source had fewer pixels than the output), `fits_max_kb` |

### Issue codes

| Code | Severity | Meaning |
|---|---|---|
| `NO_FACE` | error | no face found |
| `MULTIPLE_FACES` | error | another face at least 35% as wide as the main one |
| `FACE_TOO_SMALL` | error | fewer than 40 px between the eyes |
| `LOW_RESOLUTION` | warning | fewer than 90 px between the eyes (a commonly cited minimum for ID portraits) |
| `HEAD_TURNED` | error | the head is clearly turned to the side |
| `BLURRY` | error | sharpness below the limit |
| `TOO_DARK` / `TOO_BRIGHT` | error | mean brightness of the face outside 70-200 (of 255) |
| `UNEVEN_LIGHTING` | warning; error above twice the limit | one side of the face much darker |
| `LOW_CONTRAST` | warning | flat, washed-out face |
| `OVEREXPOSED` | warning | more than 8% of the face burnt white |
| `FACE_CUT_OFF` | warning | the face touches the edge of the image |
| `LOW_CONFIDENCE` | warning | the detector is not sure it is a face |

Codes are never renamed; new ones may be added, so treat unknown codes as generic warnings/errors by
`severity`.

### Error responses

```json
{ "error": { "code": "IMAGE_TOO_LARGE", "message": "Image is 14.2 MB; the limit is 10.5 MB." } }
```

| Status | Code | When |
|---|---|---|
| 400 | `INVALID_IMAGE` | empty, corrupt, unsupported format, malformed JSON/base64, missing `image` field |
| 400 | `UNKNOWN_PROFILE`, `INVALID_FORMAT` | bad `profile` / `format` parameter |
| 401 | `UNAUTHORIZED` | missing or wrong API key |
| 413 | `IMAGE_TOO_LARGE` | over `max_upload_mb` or `max_megapixels` |
| 422 | `NO_FACE` | `/v1/crop` on an image without a face |
| 503 | `BUSY` | every worker busy for `queue_timeout_seconds`; retry |
| 500 | `INTERNAL_ERROR` | unexpected; details in the service log |

## Client examples

### curl

```bash
curl -H "X-API-Key: $KEY" -F image=@photo.jpg "http://server:8080/v1/process?profile=badge"
curl -H "X-API-Key: $KEY" -F image=@photo.jpg "http://server:8080/v1/crop?format=jpeg" -o face.jpg
```

### C# (.NET 6+)

```csharp
using System.Net.Http.Json;
using System.Text.Json;

var http = new HttpClient { BaseAddress = new Uri("http://server:8080") };
http.DefaultRequestHeaders.Add("X-API-Key", key);

using var form = new MultipartFormDataContent();
form.Add(new ByteArrayContent(File.ReadAllBytes("photo.jpg")), "image", "photo.jpg");
var response = await http.PostAsync("/v1/process?profile=badge", form);
var result = await response.Content.ReadFromJsonAsync<JsonElement>();

if (result.GetProperty("passed").GetBoolean())
{
    var jpeg = Convert.FromBase64String(result.GetProperty("crop").GetProperty("image_base64").GetString()!);
    File.WriteAllBytes("face.jpg", jpeg);
}
else
{
    foreach (var issue in result.GetProperty("issues").EnumerateArray())
        Console.WriteLine($"{issue.GetProperty("code")}: {issue.GetProperty("message")}");
}
```

### Python

```python
import base64, requests

with open("photo.jpg", "rb") as f:
    r = requests.post(
        "http://server:8080/v1/process",
        params={"profile": "badge"},
        headers={"X-API-Key": key},
        files={"image": f},
        timeout=30,
    )
r.raise_for_status()
data = r.json()
if data["passed"]:
    open("face.jpg", "wb").write(base64.b64decode(data["crop"]["image_base64"]))
else:
    print([i["code"] for i in data["issues"]])
```

### JavaScript (browser or Node 18+)

```js
const form = new FormData();
form.append("image", file);                 // a File/Blob from <input type="file"> or a camera capture
const r = await fetch("http://server:8080/v1/process?profile=badge", {
  method: "POST", body: form, headers: { "X-API-Key": key },
});
const data = await r.json();
if (!data.passed) showProblems(data.issues.map(i => i.code));
```

From a browser page on another origin, add that origin to `server.cors_origins`. Do not ship the API key to
public browsers; call the service from your back end instead.

### PowerShell

```powershell
$r = Invoke-RestMethod -Method Post -Uri "http://server:8080/v1/process?profile=badge" -Headers @{ "X-API-Key" = $key } -Form @{ image = Get-Item .\photo.jpg }; if ($r.passed) { [IO.File]::WriteAllBytes("$PWD\face.jpg", [Convert]::FromBase64String($r.crop.image_base64)) } else { $r.issues.code }
```

(`-Form` needs PowerShell 7. On Windows PowerShell 5.1, send JSON:
`-Body (@{ image_base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("$PWD\photo.jpg")) } | ConvertTo-Json) -ContentType application/json`.)
