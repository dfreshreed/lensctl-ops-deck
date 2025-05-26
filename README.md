# 🔍 Lens API Python

The `room_trooper.py` script is designed to help you manage room metadata in your Lens Tenant. It allows you to query and update rooms. Fields like `capacity`, `size`, and `floor` are crucial for Lens Insights and Analytics. If your Tenant has rooms without this data, this tool helps you handle updating them efficiently.

---

## 🚀 Features

- Authenticates using OAuth2 Client Credentials
- Exports all rooms from your Lens tenant to the `room_data.csv` file
- Reads room data from `room_data.csv` and udpates it in your Lens Tenant
- Colorized, styled CLI output readability, logging, and error reporting

---

## 🧰 CLI Options

Running the script provides the following options:

![CLI Prompt Options](assets/roomTrooperMenu.png)

 0. `Exit the script`
 1. `Export your Lens Room Data to CSV` - Runs a `query` that returns all rooms from your Lens tenant and writes them to a `room_data.csv`.
    - `roomName` and `siteName` are returned alongside their `Ids` and written to `room_data.csv`. This makes it easier for you to identify the room and provide `capacity`, `size`, and `floor` values for import.
 2. `Update your Lens Room Data from CSV` - Reads the rooms data from `room_data.csv` and runs a `mutation` to update them in Lens.
    - For each room imported, the `roomId`, `tenantId` and `siteId` are **required**. The `roomName` and `siteName` aren't used, even if they're in the `.csv`.

   > Options 1 and 2 utilize the `room_data.csv` file in the project root directory.

If you already have the `tenantId`, `siteId`, `roomId`, feel free to edit the `room_data.csv` file with the information found in [CSV Format](./README.md#-csv-format).

---

## 📁 Project Structure

```
lens-api-python/
├── room_trooper.py                # CLI script and main file you'll run
├── requirements.txt               # Python dependencies
├── room_data.csv                  # CSV used for import and export
├── .env.example                   # Example environment variable file
├── .gitignore                     # Files and folders to ignore in git
├── update_room_data.py            # File containing query and mutation logic
├── env_helper_util.py             # File containing helper functions
└── README.md                      # Project documentation
```

---

## 📦 Requirements

- Python 3.8+
- `requests`, `pandas`, `python-dotenv`, `coloredlogs`, `pygments`, `rich`

### ⚙️ Setup Steps

To use the script, follow these setup steps (in order):

#### Clone the repo

```bash
git clone https://github.com/dfreshreed/lens-api-python.git
cd lens-api-python
```

#### Setup virtual environment

This is important to prevent dependency conflicts and avoid distrupting your global Python install.

##### **On Mac/Linux**:

```bash
python3 -m venv venv # unless you've aliased python=python3 in your shell config
source venv/bin/activate
```

##### **On Windows**:

```bash
python -m venv venv
venv\Scripts\activate
```

#### Install dependencies

```bash
pip install -r requirements.txt
```

#### Set environment variables

Copy `.env.example` to create a local `.env`

```bash
cp .env.example .env
```

Replace the placeholder text with your API Credentials, Tenant ID, and Site ID `.env`:

```bash
CLIENT_ID=your-client-id
CLIENT_SECRET=your-client-secret
TENANT_ID=your-tenant-id
SITE_ID=your-site-id # only required if you're batching this process by site
```

#### 📂 CSV Format

If you don't `export` your rooms using the script, rename your `.csv` to `room_data.csv` (the script expects this filename) and verify it contains the following headers required for `import`:

> If you are batching room updates by site (instead of all rooms in the tenant), you can add the `siteId` to the `.env` and exclude it from the `.csv` header.

```
id,capacity,size,floor,siteId
```

Expected types and data format:

| Column     | Type    | Description                                                |
| ---------- | ------- | ---------------------------------------------------------- |
| `id`       | String  | The unique Lens-generated room ID                          |
| `capacity` | Integer | Maximum number of people the room can accommodate          |
| `size`     | Enum    | One of: NONE, FOCUS, HUDDLE, SMALL, MEDIUM, LARGE          |
| `floor`    | String  | Name of the floor the room is on (e.g. "1", "2nd", "Main") |
| `siteId`    | String  | The Site ID associated with the Room (optional if in .env) |

---

## 🧠 Usage

Run the script after configuring your `.env` variables:

```bash
# Mac/Linux
source venv/bin/activate
python3 room_trooper.py

# Windows
venv\Scripts\activate
python room_trooper.py
```

---
## 🖥️ Windows-Specific Notes

If you're on Windows:

- Use `python` instead of `python3`
- Activate the virtual environment with:
    ```bash
    venv\Scripts\activate
    ```
- Save CSV files as UTF-8 (not UTF-16/ANSI). In Excel, select:
"CSV UTF-8 (Comma delimited) (*.csv)"
- If you see weird line breaks, run:

    ```bash
    git config core.autocrlf true
    ```
---

## 🧪 Example Output

The CLI will output styled responses, showing GraphQL success/error details:

Export:

```css
[DROID] RT-L-T fully operational.
[DROID] Exported 4 rooms to room_data.csv.
```

Import:

```css
2025-05-24 23:52:56 | [INFO] | Row 0 updated:
{
  "data": {
    "upsertRoom": {
      "name": "Daniel Reed Desk",
      "id": "03b9975c-5b2a-4007-9ef1-034ec756d3b4",
      "capacity": 1,
      "size": "SMALL",
      "updatedAt": "2025-05-25T03:52:56.794Z",
      "floor": "1"
    }
  }
}

2025-05-24 23:52:56 | [INFO] | 🏁 update_rooms() completed successfully with no errors.

```

## 🛡️ Security

Never commit your `.env` file. It's already been added to the `.gitignore` for safety.
