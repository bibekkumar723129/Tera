# Tera

Terabox video downloader Telegram bot with MongoDB user tracking, restart notifications, and download statistics.

## Features

✅ **Download Terabox Videos** - Download videos directly from Terabox links  
✅ **MongoDB Integration** - Track users, downloads, and activity  
✅ **Starter Messages** - Welcome new users with personalized greeting  
✅ **Restart Notifications** - Notify all users when bot restarts  
✅ **Download Tracking** - Keep statistics on user downloads  
✅ **Admin Notifications** - Send restart stats to admin user  

## Prerequisites

- Python 3.8+
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- MongoDB instance (local or MongoDB Atlas cloud)
- pip (Python package manager)

## Local Setup

### 1. Clone Repository
```bash
git clone https://github.com/strange12345678/Tera.git
cd Tera
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Setup Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` and add your credentials:
```env
# Required
BOT_TOKEN=your_telegram_bot_token_here
MONGODB_URL=mongodb+srv://username:password@cluster.mongodb.net/

# Optional but recommended
ADMIN_ID=your_telegram_user_id
MONGODB_DB_NAME=terabox_bot
DOWNLOAD_DIR=./downloads
LOG_LEVEL=INFO
```

### 4. Get Your Telegram User ID
- Send `/start` to [@userinfobot](https://t.me/userinfobot) on Telegram
- Copy your user ID and paste in `.env` as `ADMIN_ID`

### 5. Setup MongoDB

**Option A: MongoDB Atlas (Cloud - Recommended)**
1. Go to [mongodb.com/cloud/atlas](https://mongodb.com/cloud/atlas)
2. Create a free account and cluster
3. Get your connection string: `mongodb+srv://username:password@cluster.mongodb.net/`
4. Paste in `.env` as `MONGODB_URL`

**Option B: Local MongoDB**
```bash
# Install MongoDB (Ubuntu/Debian)
sudo apt-get install mongodb

# Start MongoDB
sudo systemctl start mongodb

# Connection string in .env
MONGODB_URL=mongodb://localhost:27017
```

### 6. Run the Bot
```bash
python main.py
```

The bot should output:
```
==================================================
Terabox Video Downloader Bot
==================================================
Initializing Terabox Downloader Bot...
Download directory: ./downloads
MongoDB connected successfully
Bot instance created
Starting bot...
Bot is running!
```

## Deploy to Render

### 1. Connect Your Repository
1. Push your code to GitHub
2. Go to [render.com](https://render.com)
3. Create new "Background Worker" service
4. Connect your GitHub repository

### 2. Set Environment Variables
In Render dashboard, set **Environment**:
- `BOT_TOKEN` - Your Telegram bot token
- `MONGODB_URL` - Your MongoDB connection string
- `ADMIN_ID` - Your Telegram user ID
- `MONGODB_DB_NAME` - terabox_bot (or your preferred name)

### 3. Deploy
- Render automatically detects `render.yaml`
- Click "Deploy" and wait for build completion
- Check logs to ensure bot started successfully

**Cost:** Free tier includes 1 free background worker

## Project Structure

```
Tera/
├── main.py                 # Bot entry point
├── config.py              # Configuration & env vars
├── requirements.txt       # Python dependencies
├── .env.example           # Example environment file
├── Procfile               # Deployment config for Render
├── render.yaml            # Render service config
├── README.md              # This file
└── src/
    ├── __init__.py
    ├── database.py        # MongoDB user management
    └── handlers/
        ├── __init__.py
        ├── bot.py         # Main bot handler
        └── download.py    # Terabox download logic
```

## Commands

- `/start` - Start bot and register user
- `/help` - Show help and command list
- `/cancel` - Cancel current download operation

## How It Works

1. User sends `/start` → Added to MongoDB database
2. User sends Terabox link → Bot downloads video via iTeraPlay API
3. Bot uploads video to Telegram (if under 2GB limit)
4. Download count incremented in database
5. Bot restarts → Notification sent to all users + admin with stats

## Troubleshooting

**Bot not responding:**
- Check `BOT_TOKEN` is correct in `.env`
- Verify internet connection
- Check logs: `cat bot.log`

**MongoDB connection failed:**
- Verify `MONGODB_URL` is correct
- Check IP whitelist on MongoDB Atlas (allow 0.0.0.0/0 for testing)
- Ensure MongoDB service is running (if local)

**Download fails:**
- Check if Terabox link is valid
- Verify file size is under 2GB
- Check internet speed for large files

## API Integration

This bot uses:
- **Telegram Bot API** via `python-telegram-bot` library
- **iTeraPlay API** for Terabox video streaming
- **MongoDB** for user data persistence

## License

MIT License

## Support

For issues or questions:
- Check existing issues on GitHub
- Review logs in `bot.log`
- Test with `/help` command in Telegram
