# Tera

Terabox video downloader Telegram bot.

**Deploy to Render**

- This bot runs as a long-running background worker (it uses long-polling).
- Use Render's **Background Worker** (not a web service) or use the provided `render.yaml`.

Quick steps to deploy:

1. Create a new **Background Worker** service on Render or connect your repository and let Render detect `render.yaml`.
2. Set the following environment variables in the Render dashboard (Secrets):
	- `BOT_TOKEN` — your Telegram bot token
	- Optional: `DOWNLOAD_DIR`, `LOG_LEVEL`, `MAX_FILE_SIZE` if you want to override defaults
3. Deploy. Render will run `pip install -r requirements.txt` (see `render.yaml`) and start the bot with `python main.py`.

Notes and recommendations:
- The filesystem on Render is ephemeral. Downloaded files are stored temporarily in `./downloads` (config default). For large or persistent storage, use external storage (S3, Cloud Storage) and update `download.py` accordingly.
- If you need HTTPS webhooks instead of polling, add a small web server and set up webhook handling; that requires a web service that binds to `$PORT`.
- Logs written to `bot.log` are ephemeral — prefer Render logs for persistent access.
