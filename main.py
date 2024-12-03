import os
from fastapi import FastAPI
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from dotenv import load_dotenv
from pydantic import BaseModel
import datetime

# Load environment variables
load_dotenv()

def get_calendar_events():
    try:
        creds = Credentials(
            token=os.getenv("GOOGLE_ACCESS_TOKEN"),
            refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET")
        )
        
        # Refresh the token if expired
        if creds.expired:
            creds.refresh(Request())
        
        service = build('calendar', 'v3', credentials=creds)
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            maxResults=10,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        return events_result.get('items', [])
    except Exception as e:
        return {"error": f"Failed to fetch calendar events: {str(e)}"}


def create_calendar_event(summary, start_time, end_time):
    try:
        creds = Credentials(
            token=os.getenv("GOOGLE_ACCESS_TOKEN"),
            refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET")
        )

        # Refresh the token if expired
        if creds.expired:
            creds.refresh(Request())

        service = build('calendar', 'v3', credentials=creds)

        # Event details
        event = {
            'summary': summary,
            'start': {
                'dateTime': start_time,
                'timeZone': 'UTC'
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'UTC'
            }
        }

        # Insert the event
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return {"success": True, "event_id": created_event.get("id")}
    except Exception as e:
        return {"success": False, "error": str(e)}


app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "Welcome to the Executive Assistant AI!"}

@app.get("/events")
def fetch_events():
    events = get_calendar_events()
    return {"events": events}

class EventRequest(BaseModel):
    summary: str
    start_time: str
    end_time: str

@app.post("/create-event")
def create_event(request: EventRequest):
    result = create_calendar_event(
        summary=request.summary,
        start_time=request.start_time,
        end_time=request.end_time
    )
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
