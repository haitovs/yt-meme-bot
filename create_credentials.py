#!/usr/bin/env python3
import os
from google_auth_oauthlib.flow import InstalledAppFlow

# The scopes we need
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def main():
    print("--- YouTube Credential Generator ---")
    
    # 1. Check for client_secrets.json
    if not os.path.exists("client_secrets.json"):
        print("❌ Error: 'client_secrets.json' not found.")
        print("Please download your OAuth 2.0 Client ID JSON from Google Cloud Console")
        print("and save it as 'client_secrets.json' in this folder.")
        return

    # 2. Run the OAuth flow
    print("Opening browser for authentication...")
    flow = InstalledAppFlow.from_client_secrets_file(
        "client_secrets.json", SCOPES
    )
    creds = flow.run_local_server(port=0)

    # 3. Save the credentials
    output_file = "channels/my_channel.json"
    os.makedirs("channels", exist_ok=True)
    
    with open(output_file, "w") as token:
        token.write(creds.to_json())
    
    print(f"\n✅ Success! Credentials saved to: {output_file}")
    print("You can now restart the bot or run ./deploy.sh")

if __name__ == "__main__":
    main()
