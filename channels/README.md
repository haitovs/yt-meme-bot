# YouTube channel credentials

Place the authorized user JSON files generated after completing the OAuth consent flow in this folder. Each file should contain the refresh token and scopes granted for one YouTube channel, for example:

```json
{
  "token": "ya29.a0ARrdaM...",
  "refresh_token": "1//0gZabc...",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "1234567890-abc123.apps.googleusercontent.com",
  "client_secret": "GOCSPX-XXXX",
  "scopes": [
    "https://www.googleapis.com/auth/youtube.upload"
  ]
}
```

These files are ignored by git so you don't accidentally commit real credentials. Use one file per YouTube channel/account you want to upload to.
