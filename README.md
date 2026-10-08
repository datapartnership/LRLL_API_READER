# DDPLRLL Dataset Reader

Python client for the **Low Resource Language Library API**.  
It does two things:

- **Sample** (`run`): queries `/api/collections/query` for a random sample of up to 100 text, audio, or video files, downloads them (including audio/video transcriptions), and saves a local JSON-LD with rewritten file paths.
- **Download whole collections** (`download_collections` / `download-all`): downloads **every** file of each matching audio/video collection as a bundle. See [Downloading whole collections](#downloading-whole-collections).

## Installation

```bash
# From the project root (editable / dev install)
pip install -e .
```

## Configuration

The Python reader loads `DDPLRLL_` settings from environment variables or `.env`. The CLI takes its settings as options (see [CLI Usage](#cli-usage)); for its API URL, pass `--api-url` or export `DDPLRLL_API_BASE_URL` in your shell.

### Authentication: paste your token into `tokens.json`

The reader sends a bearer token that it reads from `tokens.json` in the project root. You create this file yourself and paste the token into it by hand. It has exactly one field:

```json
{"access_token": "PASTE_THE_RAW_LRLL_API_ACCESS_TOKEN_HERE"}
```

To get the token:

1. Sign in to the web app (SPA) in your browser.
2. Open the developer tools (**Network** panel) and select any request to the LRLL API.
3. Copy the value of its `Authorization` request header, **without** the `Bearer ` prefix.
4. Paste it as the `access_token` value in `tokens.json` and save the file.

Do not use an ID token or a Microsoft Graph token. Tokens expire; when requests start failing with `401 Unauthorized`, copy a fresh token and paste it in again. `tokens.json` is git-ignored, so never commit it or share it.

Pasting the token needs no redirect URI, callback port, or `.env` authentication settings. Run commands from the project root so the default `tokens.json` path resolves to the same file. To use a different token for one CLI command, pass `--api-token`.

### Optional: Microsoft Entra SPA browser sign-in

For an Entra app registered as a **Single-page application**, run:

```bash
python textWithSpaAuth.py
# Or download a sound sample using the same browser sign-in:
python soundWithSpaAuth.py
```

Set these in `.env` or the environment (see `.env.example`):

```dotenv
ENTRA_TENANT_ID=YOUR_TENANT_ID
ENTRA_CLIENT_ID=YOUR_SPA_CLIENT_ID
ENTRA_API_SCOPE=api://YOUR_API_APP_ID/access_as_user
ENTRA_SPA_REDIRECT_URI=http://localhost:5173/callback
ENTRA_SPA_TIMEOUT_SECONDS=300
```

Use the delegated **LRLL API** scope granted to your app, not a Microsoft Graph
scope. The redirect URI must be registered exactly under the SPA platform. Stop
any development server using port **5173** first; the helper cannot silently use
another unregistered port. Other registered `http://localhost:<port>` callbacks
are supported, including a root callback such as `http://localhost:5071`.

Python hosts a temporary loopback-only page and opens your default browser.
The page uses authorization code flow with PKCE, validates OAuth state, and
redeems the code **in the real browser**. It sends the access token back to
Python through a protected, one-time local handoff. No client secret, browser
impersonation headers, JavaScript build, or additional dependencies are needed.
The browser must be able to reach `login.microsoftonline.com`, and Entra consent
and tenant policies still apply. Browser authentication always uses normal TLS
validation; the example's API SSL setting does not affect sign-in.

The SPA sign-in scripts sign in on each run and use the token in memory to download
the same samples as their `WithSpaToken` counterparts. They do **not** overwrite
`tokens.json`. The text SPA examples and all sound examples print the user's name
and username from the access token when
available, falling back to a user ID or an explicit unavailable message. These
JWT claims are decoded for display only, not verified or used for authorization;
loading a pasted token does not establish that it is valid or unexpired.
The token itself is never printed.
Keep the sign-in tab open until it reports completion. Closing it early leads
to a timeout; restart the script or use Ctrl+C to cancel. Errors and the default
five-minute timeout are reported in the terminal. Tokens are not automatically
refreshed; sign in again when a fresh token is needed.

For other Python workflows:

```python
from ddplrll_reader import EntraConfig, acquire_api_token_spa, login_entra_spa

result = acquire_api_token_spa(EntraConfig())  # Token in memory only
token = result["access_token"]

# Alternatively, explicitly sign in and save an access token to tokens.json.
# login_entra_spa(EntraConfig())
```

Existing `acquire_api_token` / `login_entra` use **MSAL Python's desktop flow**.
They require a Mobile and desktop applications redirect registration and use
`ENTRA_CALLBACK_PORT`; that setting does not control the SPA callback. A desktop
flow cannot redeem a code for a SPA-only redirect URI. See Microsoft's
[SPA redirect requirements](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow#redirect-uris-for-single-page-apps-spas).

### Optional: sign in with Keycloak instead of pasting

`kloakAzure.py` signs in through Keycloak. Run `python kloakAzure.py`, log in in the browser window that opens, and the script saves the tokens to `tokens.json`. It only signs you in; to query and download, run `ddplrll-reader` or one of the example scripts afterwards. It uses the `LowResourceLanguageDataTrust` realm at `https://lrllkeyclock.azurewebsites.net` by default. To use another Keycloak host, realm, or client, edit the `CONFIG` values at the top of the script.

### Example scripts

Run an example script from the project root. The `WithSpaToken` examples read
`tokens.json` directly; there is no interactive prompt. `textWithSpaAuth.py` and
`soundWithSpaAuth.py` instead sign in through the browser.

| Script | Query |
|---|---|
| `nsoWithSpaToken.py` | **All** audio from the provider `National Statistics Office`, each with its transcript → `output/nso/<collection id>/` (see [Downloading whole collections](#downloading-whole-collections)) |
| `soundWithSpaToken.py` | A random sample of 2 audio files in Chichewa (`ny`) from 2026 → `output/sound/` |
| `soundWithSpaAuth.py` | Browser SPA sign-in, then the same 2-file sound sample → `output/sound/` |
| `textWithSpaToken.py` | A random sample of 10 text files matching `malaria` → `output/text/` |
| `textWithSpaAuth.py` | Browser SPA sign-in, then the same 10-file text sample → `output/text/` |

The sound and text scripts save the files to `<output>/files/` and the metadata to `<output>/dataset.jsonld`. Edit the constants at the top of a script as needed. Set `API_BASE_URL` to the API host called by the SPA, e.g. `https://lrldtmetadataqa.worldbank.org/`.

## CLI Usage

The CLI has three commands:

- `run` downloads a **random sample** of up to 100 files of any media type.
- `download-all` downloads **every** file of each matching audio/video collection.
- `health` checks that the API is up.

The CLI defaults to `http://localhost:5000`, so the examples below specify `--api-url`. You can instead export `DDPLRLL_API_BASE_URL=https://lrldtmetadataqa.worldbank.org` in your shell.

Options shared by all commands:

| Flag | Default | Description |
|---|---|---|
| `--api-url`, `-u` | `http://localhost:5000` | Base URL of the API; can also be set with an exported `DDPLRLL_API_BASE_URL` |
| `--api-token`, `-k` | from `tokens.json` | Bearer token for this command only (`run` and `download-all`) |
| `--no-verify-ssl` | off | Skip SSL certificate verification (e.g. behind a proxy) |

`run` options:

| Flag | Default | Description |
|---|---|---|
| `--media-type`, `-m` | — | `Text`, `Audio`, or `Video` |
| `--provider`, `-P` | — | Provider name (partial, case-insensitive), e.g. `National Statistics Office` |
| `--collection-id` | — | Restrict to a single collection |
| `--language`, `-L` | — | Collection language name or code (partial), e.g. `nya` |
| `--keyword`, `-K` | — | File or collection keyword (partial) |
| `--theme`, `-t` | — | File or collection theme (partial) |
| `--author`, `-a` | — | Text file author (partial) |
| `--year`, `-y` | — | Text publication year, or a year inside the collection's coverage |
| `--limit`, `-l` | `30` | Max file entries (1–100). The API returns a **random sample** of this size; to get everything, use `download-all` |
| `--output`, `-o` | `./output` | Output directory |
| `--no-download` | off | Save the JSON-LD only; skip downloading files |
| `--concurrency`, `-c` | `5` | Parallel downloads |
| `--file-timeout` | `300` | Max seconds for a single file download |
| `--verbose`, `-v` | off | Debug logging |

`download-all` options:

| Flag | Default | Description |
|---|---|---|
| `--media-type`, `-m` | — | `Audio` or `Video`; text collections are always skipped |
| `--provider`, `-P` | — | Provider name (partial, case-insensitive) |
| `--language`, `-L` | — | Collection language name or code (partial) |
| `--theme`, `-t` | — | Collection theme (partial) |
| `--year`, `-y` | — | A year inside the collection's coverage |
| `--output`, `-o` | `./output` | Collections are extracted to `<output>/<collection id>/` |
| `--keep-zip` | off | Keep each collection's ZIP after extracting it |
| `--verbose`, `-v` | off | Debug logging |

```bash
# First, paste your access token into tokens.json (see "Authentication").

# A random sample of 10 files from one provider
ddplrll-reader run \
  --api-url https://lrldtmetadataqa.worldbank.org \
  --provider "National Statistics Office" \
  --limit 10 \
  --output ./nso-output

# Text files
ddplrll-reader run --api-url https://lrldtmetadataqa.worldbank.org --media-type Text --keyword malaria --year 2024

# Audio in Chichewa, metadata only
ddplrll-reader run --api-url https://lrldtmetadataqa.worldbank.org --media-type Audio --language nya --no-download

# Every audio file from one provider, in full (see "Downloading whole collections")
ddplrll-reader download-all --api-url https://lrldtmetadataqa.worldbank.org \
  --provider "National Statistics Office" --media-type Audio --output ./nso-output

# Health check
ddplrll-reader health --api-url https://lrldtmetadataqa.worldbank.org

# Optional: override token from tokens.json for one command
ddplrll-reader run --api-url https://lrldtmetadataqa.worldbank.org --api-token MY_TOKEN --keyword education
```

## Python API

```python
from ddplrll_reader import DdplrllDatasetClient, Settings

# First, paste your access token into tokens.json (see "Authentication").

# Configure
settings = Settings(
    api_base_url="https://lrldtmetadataqa.worldbank.org",
    output_dir="./output",
)

client = DdplrllDatasetClient(settings)

# Full pipeline: query → download files → save dataset.jsonld
jsonld_path = client.run(provider="National Statistics Office", limit=10)
print(f"Saved to {jsonld_path}")

# Filters: media_type, collection_id, provider, language, keyword, theme, author, year, limit
text_path = client.run(media_type="Text", keyword="malaria", year=2024, output_dir="./output/text")
audio_path = client.run(media_type="Audio", language="nya", limit=20, output_dir="./output/audio")

# Query only (returns raw dict)
data = client.query(media_type="Text", theme="Education")

# Query with Pydantic validation
response = client.query_validated(keyword="malaria")
for dataset in response.graph or []:
    print(dataset.sc_name, dataset.ddpv_media_type)
    for f in dataset.distribution or []:
        print(f"  {f.sc_name} → {f.sc_content_url}")
        if f.ddpv_transcription:
            print(f"    transcription → {f.ddpv_transcription.sc_content_url}")
```

## Downloading whole collections

`run` and `query` use `/api/collections/query`, which returns a **random sample** of at most 100 files per call; repeated calls overlap and never guarantee a complete set. To download everything, use `download_collections` (or `ddplrll-reader download-all`):

1. It lists every matching collection from the paged catalog (`/api/catalog/collections`).
2. For each audio/video collection it downloads the bundle ZIP (`/api/collections/{id}/bundle`), which holds **every** media file followed by its transcription, plus a `metadata.jsonld` Croissant document.
3. It extracts the ZIP to `<output>/<collection id>/` and deletes it (pass `keep_zip=True` / `--keep-zip` to keep it).
4. It rewrites every `sc:contentUrl` in `metadata.jsonld`, including those of nested `ddpv:transcription` objects, from the API URL to the absolute path of the extracted file. Files missing from the bundle keep their API URL.

```python
client = DdplrllDatasetClient(Settings(api_base_url="https://lrldtmetadataqa.worldbank.org", output_dir="./output/nso"))

# Filters: media_type, provider, language, theme, year
folders = client.download_collections(provider="National Statistics Office", media_type="Audio")

# Just list what would be downloaded
for c in client.list_collections(provider="National Statistics Office"):
    print(c["id"], c["mediaType"], c["items"], "files")
```

```
output/nso/
└── MW-NYA-NSO-AUD-001/
    ├── metadata.jsonld        # Croissant JSON-LD for the whole collection, with local file paths
    ├── <recording>.wav
    ├── <recording>.txt        # its transcription
    ├── ...
    └── MISSING_FILES.txt      # only if some files were missing on the server
```

Notes:

- **Text collections are skipped**; the API cannot bundle them. `run` can only fetch a random sample of up to 100 text files per call; there is no complete text download in this library yet.
- **Bundles can be several GB** and download as a single stream, one collection at a time. Progress is logged every 500 MB.
- **Re-running is safe.** Collections whose folder already exists are not downloaded again; only their `metadata.jsonld` URLs are rewritten (which also fixes folders downloaded by older versions). An interrupted download restarts that collection from the beginning, because the ZIP is generated on the fly and cannot be resumed.
- **The access token is checked when each collection's download starts.** If later collections fail with 401, sign in again and re-run; finished collections are skipped.

## Output Structure (`run`)

`run` and the sound/text example scripts write:

```
output/
├── dataset.jsonld          # Croissant JSON-LD with local file paths
└── files/
    ├── 1367_combined_seg0001_151267-152333.wav   # audio file
    ├── 1367_combined_seg0001_151267-152333.txt   # its transcription
    ├── report.txt                                # text file (served as plain text, even for PDFs)
    └── ...
```

Files keep their original `sc:name`, so each recording sits next to its transcript. If two files in one download share a name, the second gets its file id appended (e.g. `report-file-1a2b3c4d5e6f7a8b.txt`).

After downloading, each `sc:contentUrl` in the JSON-LD (including those of nested `ddpv:transcription` objects) is rewritten from the remote URL to the absolute local path, e.g.:

```
"sc:contentUrl": "http://localhost:5000/api/files/file-1a2b3c4d5e6f7a8b"
→
"sc:contentUrl": "/Users/you/output/files/report.txt"
```

## Using with pandas

```python
import json
import pandas as pd

# Load the JSON-LD
with open("output/dataset.jsonld") as f:
    data = json.load(f)

# Flatten all file objects across every dataset/year into a DataFrame
rows = []
for dataset_node in data.get("@graph", []):
    dataset_id = dataset_node.get("@id")
    year = dataset_node.get("sc:temporalCoverage")
    for file_obj in dataset_node.get("distribution", []):
        rows.append({
            "dataset_id": dataset_id,
            "year": year,
            "file_id": file_obj.get("@id"),
            "name": file_obj.get("sc:name"),
            "author": file_obj.get("sc:author"),
            "local_path": file_obj.get("sc:contentUrl"),
            "size_bytes": file_obj.get("sc:contentSize"),
            "word_count": file_obj.get("sc:wordCount"),
            "token_count": file_obj.get("ddpv:tokenCount"),
            "keywords": file_obj.get("sc:keywords"),
            "themes": file_obj.get("dcat:theme"),
        })

df = pd.DataFrame(rows)
print(df.head())
print(f"\nTotal files: {len(df)}")
print(f"Total tokens: {df['token_count'].sum():,}")
```

## Using with Hugging Face Datasets

```python
import json
from datasets import Dataset

with open("output/dataset.jsonld") as f:
    data = json.load(f)

# Build a flat list of records
records = []
for dataset_node in data.get("@graph", []):
    for file_obj in dataset_node.get("distribution", []):
        records.append({
            "file_id": file_obj["@id"],
            "name": file_obj.get("sc:name"),
            "author": file_obj.get("sc:author"),
            "year": dataset_node.get("sc:temporalCoverage"),
            "local_path": file_obj.get("sc:contentUrl"),
            "word_count": file_obj.get("sc:wordCount"),
            "token_count": file_obj.get("ddpv:tokenCount"),
            "keywords": ", ".join(file_obj.get("sc:keywords", [])),
            "themes": ", ".join(file_obj.get("dcat:theme", [])),
        })

ds = Dataset.from_list(records)
print(ds)
print(ds[0])

# Filter, shuffle, split
ds_health = ds.filter(lambda r: "Health" in r["themes"])
train_test = ds_health.train_test_split(test_size=0.2)
print(train_test)
```


## End-to-end: query → pandas → analysis

```python
from ddplrll_reader import DdplrllDatasetClient, Settings
import pandas as pd

# First, paste your access token into tokens.json (see "Authentication").

# 1. Query and download
client = DdplrllDatasetClient(Settings(
    api_base_url="https://lrldtmetadataqa.worldbank.org",
))
jsonld_path = client.run(keyword="health", year=2023, limit=50)

# 2. Load into pandas
import json
with open(jsonld_path) as f:
    data = json.load(f)

rows = [
    {
        "name": fo.get("sc:name"),
        "author": fo.get("sc:author"),
        "words": fo.get("sc:wordCount"),
        "tokens": fo.get("ddpv:tokenCount"),
        "themes": fo.get("dcat:theme"),
        "path": fo.get("sc:contentUrl"),
    }
    for node in data.get("@graph", [])
    for fo in node.get("distribution", [])
]
df = pd.DataFrame(rows)

# 3. Analyse
print(df.describe())
print(df.groupby("author")["tokens"].sum().sort_values(ascending=False))
```

## License

MIT
