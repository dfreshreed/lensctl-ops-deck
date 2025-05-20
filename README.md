# 🔍 Lens API Python

A Python script (`update_room_data.py`) that reads room metadata from a CSV file and adds or updates room records programmatically using the Lens API `upsertRoom` mutation.

---

## 🚀 Features

- Reads room data from a CSV file
- Authenticates using OAuth2 client credentials
- Sends GraphQL mutations to update room metadata
- Colorized output for logging and error reportiong

---

## 📦 Requirements

- Python 3.8+
- `requests`, `pandas`, `python-dotenv`, `coloredlogs`, `pygments`

Install all requirements:
```bash
pip install -r requirements.txt
```

## ⚙️ Setup

1. Clone the repo

```bash
git clone https://github.com/dfreshreed/lens-api-python.git
cd lens-api-python
```

2. Setup virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies

```bash
pip install -r requirements.txt
```

4. Set environment variables
   
Copy the template and fill in your API credentials

```bash
cp .env.template .env
```

Edit `.env`:
```bash
CLIENT_ID=your-client-id
CLIENT_SECRET=your-client-secret
TENANT_ID=your-tenant-id
SITE_ID=your-site-id
```
## 📂 CSV Format
Your `room_data.csv` should contain the following headers:
```
id,capacity,size,floor
```
Each row represents one room to update. 

Expected types and data format:

```
"id" ➡️ the unique Lens generated room id
```

```
"capacity" Integer (number) the max number of people the room can accomodate
```

```
"size" ➡️ Enum that expects one of the following values
NONE
FOCUS
HUDDLE
SMALL
MEDIUM
LARGE
```

```
"floor" ➡️ String the name of the floor
```

## 🧠 Usage
After you've added your `.env` variables and updated the `room_data.csv` file, run:
```bash
source venv/bin/activate
python update_room_data.py
```

## 🧪 Example Output
```bash
2025-05-20 09:15:11 dfr-machine.local __main__[84359] INFO Row 0 updated:
{
  "data": {
    "upsertRoom": {
      "name": "Room 1",
      "id": "8f366119-...a",
      "capacity": 4,
      "size": "SMALL",
      "updatedAt": "2025-05-06T21:27:15.589Z",
      "floor": "1"
    }
  }
}
```

## 🛡️ Security
Never commit your `.env` file. It's already been added to the .gitignore for safety.
