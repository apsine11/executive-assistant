import os
from openai import OpenAI
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from datetime import datetime, timezone
import json
import re

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Google Calendar Helper Functions
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


# Request Schema for Parsing Commands
class CommandRequest(BaseModel):
    command: str

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.post("/parse-command")
def parse_with_gpt(request: CommandRequest):
    """
    Parse a natural language command using GPT-4 and create a Google Calendar event.
    """
    # Get the current date dynamically
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Prepare GPT-4 prompt
    prompt = f"""
    You are a helpful assistant. The current date is {current_date}. Your task is to extract details from the command below and return them as a JSON object.
    Output only a valid JSON object with these fields: "title", "start_time", and "end_time". ONLY INCLUDE THE JSON OUTPUT. Do not include any additional text, explanations, or formatting.

    Command: "{request.command}"

    Ensure your response is a valid JSON object. 
    
    Example:
    {{
        "title": "Team Meeting",
        "start_time": "2024-12-03T15:00:00Z",
        "end_time": "2024-12-03T16:00:00Z"
    }}
    """

    try:
        # Call GPT-4 API using the OpenAI client
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt}
            ]
        )

        # Parse the response
        parsed_data = response.choices[0].message.content
        print(f"GPT-4 Response: {parsed_data}")  # Debugging: Log the raw response

        # Extract JSON using a regular expression
        json_match = re.search(r"\{.*?\}", parsed_data, re.DOTALL)
        if not json_match:
            return {"error": "Response does not contain valid JSON"}

        # Parse the extracted JSON
        parsed_event = json.loads(json_match.group())
        print(f"parsed event: {parsed_event}")

        # Validate the parsed data
        if not all(key in parsed_event for key in ["title", "start_time", "end_time"]):
            return {"error": "Incomplete data parsed from GPT-4"}

        # Schedule the event in Google Calendar
        result = create_calendar_event(
            summary=parsed_event["title"],
            start_time=parsed_event["start_time"],
            end_time=parsed_event["end_time"]
        )
        return result

    except Exception as e:
        return {"error": f"Failed to parse command or create event: {str(e)}"}


@app.get("/")
def read_root():
    return {"message": "Welcome to the Executive Assistant AI!"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

