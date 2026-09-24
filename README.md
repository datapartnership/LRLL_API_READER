# DDPLRLL Dataset Reader

Python client for the **Low Resource Language Library API**.  
Queries Croissant JSON-LD metadata for text and sound datasets, downloads the referenced files, and saves a local JSON-LD with rewritten file paths.

## Installation

```bash
# From the project root (editable / dev install)
pip install -e .
```

## Configuration

The Python reader loads `DDPLRLL_` settings from environment variables or `.env`. The CLI also accepts the options below; for its API URL, pass `--api-url` or export `DDPLRLL_API_BASE_URL` in your shell.

Authentication uses a bearer token from `tokens.json` by default.

### Sound downloads with a token copied from the SPA

If you cannot change the Entra app registration, paste the **LRLL API access token** into the ignored `tokens.json` file in the project root:

```json
{"access_token": "PASTE_THE_RAW_LRLL_API_ACCESS_TOKEN_HERE"}
```

Use only the raw token value, without the `Bearer ` prefix. You can find it in an LRLL API request's `Authorization` header in the browser's Network panel. Do not use an ID token or a Microsoft Graph token. Then run `python soundWithSpaToken.py` from the project root. The script reads `tokens.json` directly; there is no interactive prompt.

The script downloads up to two Chichewa (`ny`) sound files from 2024 to `output/sound/files/` and saves `output/sound/sound_dataset.jsonld`. Edit `API_BASE_URL`, `LANGUAGE`, `YEAR`, and `LIMIT` at the top of the script as needed. Set `API_BASE_URL` to the API host called by the SPA. This flow needs no redirect URI, callback port, or `.env` authentication settings. Replace the token in `tokens.json` when it expires.

### Microsoft Entra ID setup for the CLI

1. Register a public client under **Mobile and desktop applications** in Microsoft Entra ID. Set its redirect URI to `http://localhost` ([Microsoft setup guide](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration)).
2. Give the client a delegated permission for the LRLL API's exposed scope and grant consent as required. Use that API scope, such as `api://<api-app-id>/access_as_user`, rather than a Microsoft Graph scope ([API scope guide](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-protected-web-api-expose-scopes)). The API deployment must accept Entra access tokens for this scope.
3. Add these values to `.env` in the project root (see `.env.example`):

   ```dotenv
   ENTRA_TENANT_ID=<directory-tenant-id>
   ENTRA_CLIENT_ID=<desktop-client-application-id>
   ENTRA_API_SCOPE=api://<api-app-id>/<scope-name>
   ENTRA_CALLBACK_PORT=8081
   ```

4. From the project root, sign in and save `tokens.json`:

   ```bash
   python -c "from ddplrll_reader import login_entra; login_entra()"
   ```

The browser sign-in uses PKCE. `ddplrll-reader run` and `ddplrll-reader sound` then read the saved **access token** from `tokens.json` and send it as a bearer token. Repeat the sign-in command when the token expires. Run commands from the project root so the default token path resolves to the same file. You can use `--api-token` to override it for one command.

`kloakAzure.py` is an alternative that signs in **and** runs the text and sound queries in one command. Use `--dataset text` or `--dataset sound` for one query, `--no-download` for metadata only, and `python kloakAzure.py --help` for filters and output paths. The script uses `https://lrllapi.azurewebsites.net` by default; pass `--api-url` for another deployment.

From Python code, the library also exposes `EntraConfig`, `acquire_api_token`, and `save_token` for separate authentication steps.

| CLI flag | Default | Description |
|---|---|---|
| `--api-url` | `http://localhost:5000` | Base URL of the API; can also be set with an exported `DDPLRLL_API_BASE_URL` |
| `--keyword` | — | Filter by keyword |
| `--theme` | — | Filter by theme (text datasets) |
| `--author` | — | Filter by author (text datasets) |
| `--year` | — | Filter by year |
| `--limit` | `30` | Max file entries (1–100) |
| `--output` | `./output` | Output directory |
| `--no-download` | off | Skip downloading referenced files |
| `--concurrency` | `5` | Parallel downloads |

## CLI Usage

The CLI defaults to `http://localhost:5000`, so the Azure examples below specify `--api-url`. You can instead export `DDPLRLL_API_BASE_URL=https://lrllapi.azurewebsites.net` in your shell.

### Text datasets (`run`)

```bash
# Sign in first using the command in "Microsoft Entra ID setup for the CLI".

# Full pipeline: query + download + save JSON-LD
ddplrll-reader run \
  --api-url https://lrllapi.azurewebsites.net \
  --keyword malaria \
  --year 2024 \
  --limit 10 \
  --output ./my-output

# Query only (no file downloads)
ddplrll-reader run --api-url https://lrllapi.azurewebsites.net --keyword health --no-download

# Health check
ddplrll-reader health --api-url https://lrllapi.azurewebsites.net

# Optional: override token from tokens.json for one command
ddplrll-reader run --api-url https://lrllapi.azurewebsites.net --api-token MY_TOKEN --keyword education
```

### Sound datasets (`sound`)

```bash
# Full pipeline: query + download audio files + save JSON-LD
ddplrll-reader sound \
  --api-url https://lrllapi.azurewebsites.net \
  --language ny \
  --year 2024 \
  --limit 20 \
  --output ./sound-output

# Filter by programme name
ddplrll-reader sound --api-url https://lrllapi.azurewebsites.net --programme "Radio Chichewa" --limit 50

# Filter by keyword, skip downloading
ddplrll-reader sound --api-url https://lrllapi.azurewebsites.net --keyword climate --no-download

# Sound health check
ddplrll-reader sound-health --api-url https://lrllapi.azurewebsites.net
```

#### Sound-specific options

| Flag | Short | Description |
|---|---|---|
| `--language` | `-L` | Filter by language code or display language (e.g. `ny`, `en-GB`) |
| `--programme` | `-p` | Filter by programme / dataset name |
| `--keyword` | `-K` | Filter by keyword |
| `--year` | `-y` | Filter by publication year |
| `--limit` | `-l` | Max audio files returned (1–100, default 30) |

## Python API

```python
from ddplrll_reader import DdplrllDatasetClient, Settings

# First, sign in with login_entra() as shown above.

# Configure
settings = Settings(
    api_base_url="https://lrllapi.azurewebsites.net",
    output_dir="./output",
)

client = DdplrllDatasetClient(settings)

# ── Text datasets ─────────────────────────────────────────────

# Full pipeline: query → download PDFs → save dataset.jsonld
jsonld_path = client.run(keyword="malaria", year="2024", limit=10)
print(f"Saved to {jsonld_path}")

# Query only (returns raw dict)
data = client.query(keyword="health", theme="Education")

# Query with Pydantic validation
response = client.query_validated(keyword="malaria")
for dataset in response.graph or []:
    print(dataset.sc_name)
    for f in dataset.distribution or []:
        print(f"  {f.sc_name} → {f.sc_content_url}")

# ── Sound datasets ────────────────────────────────────────────

# Full pipeline: query → download audio files → save sound_dataset.jsonld
sound_path = client.run_sound(language="ny", year=2024, limit=20)
print(f"Saved to {sound_path}")

# Query only (returns raw dict)
sound_data = client.query_sound(language="ny", programme="Radio Chichewa")
```

## Output Structure

```
output/
├── dataset.jsonld          # Text dataset Croissant JSON-LD with local file paths
├── sound_dataset.jsonld    # Sound dataset Croissant JSON-LD with local file paths
└── files/
    ├── file-2022-465a93ae.pdf
    ├── file-2022-1cafc7a4.pdf
    └── ...
```

After downloading, each `scContentUrl` in the JSON-LD is rewritten from the remote URL to the absolute local path, e.g.:

```
"scContentUrl": "http://localhost:5000/api/files/file-2022-465a93ae"
→
"scContentUrl": "/Users/you/output/files/file-2022-465a93ae.pdf"
```

## Using with mlcroissant

The saved `dataset.jsonld` is a valid [Croissant 1.0](https://mlcommons.org/croissant/) document.
Install the `mlcroissant` package to load it directly:

```bash
pip install mlcroissant
```

### Load and iterate records

```python
from mlcroissant import Dataset

ds = Dataset(jsonld=jsonld_path)
records = ds.records("default")

for record in records:
    print(record)
```

### Inspect metadata

```python
from mlcroissant import Dataset

ds = Dataset(jsonld="output/dataset.jsonld")

# Top-level metadata
print(ds.metadata.name)
print(ds.metadata.description)

# List all record sets
for record_set in ds.metadata.record_sets:
    print(record_set.name, "–", len(record_set.fields), "fields")
```

### End-to-end: ddplrll-reader → mlcroissant

```python
from ddplrll_reader import DdplrllDatasetClient, Settings
from mlcroissant import Dataset

# First, sign in with login_entra() as shown above.

client = DdplrllDatasetClient(Settings(api_base_url="https://lrllapi.azurewebsites.net"))

# Text datasets
jsonld_path = client.run(keyword="health", year="2023", limit=50)
ds = Dataset(jsonld=jsonld_path)
for record in ds.records("default"):
    print(record)

# Sound datasets
sound_path = client.run_sound(language="ny", limit=20)
ds_sound = Dataset(jsonld=sound_path)
for record in ds_sound.records("default"):
    print(record)
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
for dataset_node in data.get("graph", []):
    dataset_id = dataset_node.get("id")
    year = dataset_node.get("scTemporalCoverage")
    for file_obj in dataset_node.get("distribution", []):
        rows.append({
            "dataset_id": dataset_id,
            "year": year,
            "file_id": file_obj.get("id"),
            "name": file_obj.get("scName"),
            "author": file_obj.get("scAuthor"),
            "local_path": file_obj.get("scContentUrl"),
            "size_bytes": file_obj.get("scContentSize"),
            "word_count": file_obj.get("scWordCount"),
            "token_count": file_obj.get("ddpvTokenCount"),
            "keywords": file_obj.get("scKeywords"),
            "themes": file_obj.get("dcatTheme"),
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
for dataset_node in data.get("graph", []):
    for file_obj in dataset_node.get("distribution", []):
        records.append({
            "file_id": file_obj["id"],
            "name": file_obj.get("scName"),
            "author": file_obj.get("scAuthor"),
            "year": dataset_node.get("scTemporalCoverage"),
            "local_path": file_obj.get("scContentUrl"),
            "word_count": file_obj.get("scWordCount"),
            "token_count": file_obj.get("ddpvTokenCount"),
            "keywords": ", ".join(file_obj.get("scKeywords", [])),
            "themes": ", ".join(file_obj.get("dcatTheme", [])),
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

# First, sign in with login_entra() as shown above.

# 1. Query and download
client = DdplrllDatasetClient(Settings(
    api_base_url="https://lrllapi.azurewebsites.net",
))
jsonld_path = client.run(keyword="health", year="2023", limit=50)

# 2. Load into pandas
import json
with open(jsonld_path) as f:
    data = json.load(f)

rows = [
    {
        "name": fo.get("scName"),
        "author": fo.get("scAuthor"),
        "words": fo.get("scWordCount"),
        "tokens": fo.get("ddpvTokenCount"),
        "themes": fo.get("dcatTheme"),
        "path": fo.get("scContentUrl"),
    }
    for node in data.get("graph", [])
    for fo in node.get("distribution", [])
]
df = pd.DataFrame(rows)

# 3. Analyse
print(df.describe())
print(df.groupby("author")["tokens"].sum().sort_values(ascending=False))
```

## License

MIT
