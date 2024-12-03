from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

def get_tokens():
    try:
        # Print environment variables to debug
        print("GOOGLE_CLIENT_ID:", os.getenv("GOOGLE_CLIENT_ID"))
        print("GOOGLE_CLIENT_SECRET:", os.getenv("GOOGLE_CLIENT_SECRET"))
        print("GOOGLE_REDIRECT_URI:", os.getenv("GOOGLE_REDIRECT_URI"))

        # Set up the OAuth flow
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [os.getenv("GOOGLE_REDIRECT_URI")]
                }
            },
            scopes=["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/calendar.events"]
        )

        print("Starting OAuth flow. Please check your browser.")
        creds = flow.run_local_server(port=8080)

        # Print tokens
        print("Access Token:", creds.token)
        print("Refresh Token:", creds.refresh_token)

    except Exception as e:
        print("Error during OAuth flow:", str(e))

if __name__ == "__main__":
    get_tokens()
