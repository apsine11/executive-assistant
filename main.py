import os
from openai import OpenAI
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pytz import timezone
from pytz.exceptions import UnknownTimeZoneError
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from datetime import datetime, timedelta
import requests
import json
import re

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Helper function to detect user's timezone
def get_user_timezone():
    try:
        response = requests.get("https://ipinfo.io", timeout=5)
        data = response.json()
        return data.get("timezone", "UTC")  # Default to UTC if detection fails
    except Exception as e:
        print(f"Time zone detection failed: {e}")
        return "UTC"

# Google Calendar Helper Functions
def create_calendar_event(summary, start_time, end_time, user_timezone):
    try:
        creds = Credentials(
            token=os.getenv("GOOGLE_ACCESS_TOKEN"),
            refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET")
        )

        if creds.expired:
            creds.refresh(Request())

        service = build('calendar', 'v3', credentials=creds)

        event = {
            'summary': summary,
            'start': {'dateTime': start_time, 'timeZone': user_timezone},
            'end': {'dateTime': end_time, 'timeZone': user_timezone}
        }

        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return {"success": True, "event_id": created_event.get("id")}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Request Schema for Commands
class CommandRequest(BaseModel):
    command: str

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Helper function for command classification
def classify_command(command: str, attempt: int = 1) -> str:
    """
    Classify the command using GPT. Retries once if it fails on the first attempt.
    Uses fallback heuristics if GPT fails or returns an unexpected response.
    """
    prompt = f"""
    You are a helpful assistant. Classify the following command into one of the following categories:
    - "meeting-summary" 
    - "create-event"
    - "date-time-interpretation"

    Command: "{command}"
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}]
        )
        classification = response.choices[0].message.content.strip()

        # Validate classification
        if classification not in ["meeting-summary", "create-event", "date-time-interpretation"]:
            raise ValueError("Invalid classification returned by GPT.")

        return classification

    except Exception as e:
        print(f"GPT classification attempt {attempt} failed: {e}")

        if attempt == 1:
            # Try once more
            return classify_command(command, attempt=2)
        else:
            # Apply fallback heuristic
            return heuristic_classification(command)

def heuristic_classification(command: str) -> str:
    """
    Basic keyword-based fallback classification if GPT fails:
    - If command contains words like 'summarize', 'spent my time on', 'what did my week look like', classify as 'meeting-summary'
    - If command contains words like 'create', 'schedule', 'book', classify as 'create-event'
    - Otherwise, assume 'date-time-interpretation'
    """
    cmd_lower = command.lower()
    if any(keyword in cmd_lower for keyword in ["summarize", "spent my time", "what did my week look like", "last week", "this week", "next week"]):
        return "meeting-summary"
    elif any(keyword in cmd_lower for keyword in ["create", "schedule", "book", "set up"]):
        return "create-event"
    else:
        return "date-time-interpretation"

@app.post("/parse-command")
def parse_with_classification(request: CommandRequest):
    """
    Dynamically classify the user command and route to the appropriate endpoint.
    Falls back to heuristic classification if GPT fails.
    """
    try:
        classification = classify_command(request.command)
        print(f"Classified command '{request.command}' as '{classification}'")

        if classification == "meeting-summary":
            return meeting_summary_command(request)
        elif classification == "create-event":
            return interpret_and_create_event(request)
        elif classification == "date-time-interpretation":
            return interpret_command_date_time(request)
        else:
            # This should never happen with the heuristic fallback in place, but just in case:
            return {"message": "I'm having trouble understanding your request. Could you try rephrasing it?"}

    except Exception as e:
        # If something unexpected happens, return a friendly message
        print(f"Error processing command: {e}")
        return {"error": "I'm having trouble understanding your request right now. Please try again later."}


@app.post("/meeting-summary-command")
def meeting_summary_command(request: CommandRequest):
    """
    Generate a meeting summary based on user input, handling both past and future requests.
    """
    user_timezone = get_user_timezone()
    user_tz = timezone(user_timezone)

    current_date = datetime.now(user_tz).strftime("%Y-%m-%d")

    # Updated prompt to handle past, present, and future (including "next week")
    prompt = f"""
    You are a helpful assistant. Today's date is {current_date}.
    Parse the following command and identify the desired date range for summarizing meetings.

    Command: "{request.command}"

    Consider that the user may ask about past or future time periods.
    - "last week" should mean the full calendar week before today.
    - "this week" should mean the current week including today's date.
    - "next week" should mean the full upcoming calendar week, Monday through Sunday, after the current week.

    Return a JSON object with fields: "start_date" and "end_date" in YYYY-MM-DD format.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}]
        )
        parsed_data = response.choices[0].message.content
        print(f"Parsed Date Range: {parsed_data}")

        json_match = re.search(r"\{.*?\}", parsed_data, re.DOTALL)
        date_range = json.loads(json_match.group())

        # Fetch events from Google Calendar for the given date range
        creds = Credentials(
            token=os.getenv("GOOGLE_ACCESS_TOKEN"),
            refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET")
        )
        if creds.expired:
            creds.refresh(Request())
        service = build('calendar', 'v3', credentials=creds)

        start_datetime = f"{date_range['start_date']}T00:00:00Z"
        end_datetime = f"{date_range['end_date']}T23:59:59Z"

        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_datetime,
            timeMax=end_datetime,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        if not events:
            return {"message": "No meetings found in the specified date range."}

        meetings_text = "\n".join([
            f"- {event.get('summary', 'No Title')}, Start: {event['start'].get('dateTime')}, "
            f"End: {event['end'].get('dateTime')}"
            for event in events
        ])

        # Determine if the date range is in the future or past
        date_range_start = datetime.strptime(date_range["start_date"], "%Y-%m-%d").date()
        today = datetime.now(user_tz).date()
        
        if date_range_start > today:
            # Future-oriented summary
            summary_prompt = f"""
            You are a helpful assistant. The user wants a summary of their upcoming schedule based on the command:

            User Command: "{request.command}"

            Below are the meetings scheduled for the given time period:
            {meetings_text}

            Please create a natural language summary that directly addresses the user's request, focusing on the upcoming time period. 
            Consider including:
            - Types of meetings or activities planned.
            - The total number of meetings and approximate total time they might spend.
            - Any suggestions for managing their upcoming schedule.

            Present it as a helpful, friendly, and conversational answer.
            """
        else:
            # Past or current-oriented summary
            summary_prompt = f"""
            You are a helpful assistant. The user wants a summary of their meetings based on the command:

            User Command: "{request.command}"

            Below are the meetings we retrieved for the relevant time period:
            {meetings_text}

            Please create a natural language summary that directly addresses the user's request. Consider these guidelines:
            - If the user asks for a general overview, provide a high-level summary of their meetings.
            - If the user asks where they spent most of their time, highlight which activities took the majority of their schedule.
            - If the user asks about a certain metric (like total number of meetings or total hours), include that.
            - Provide one or two suggestions for improving time management if relevant.

            Your response should be helpful, friendly, and conversational.
            """

        summary_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": summary_prompt}]
        )
        gpt_summary = summary_response.choices[0].message.content
        return {"summary": gpt_summary}
    except Exception as e:
        return {"error": f"Failed to generate meeting summary: {str(e)}"}

@app.post("/interpret-and-create-event")
def interpret_and_create_event(request: CommandRequest):
    """
    Interpret a command that includes date and time references and create a calendar event.
    """
    try:
        # Step 1: Detect user's time zone
        user_timezone = get_user_timezone()  # Fetch the user's timezone dynamically
        try:
            user_tz = timezone(user_timezone)  # Ensure this is a valid timezone
        except UnknownTimeZoneError:
            user_tz = timezone("UTC")  # Fallback to UTC if detection fails

        # Step 2: Use GPT to extract event details
        current_date = datetime.now(user_tz).strftime("%Y-%m-%d")
        prompt = f"""
        You are a smart assistant helping users schedule events. Interpret the following command and extract:
        1. Event title (e.g., "Gym", "Lunch with friends").
        2. Date in YYYY-MM-DD format (e.g., 2024-12-15). Assume today's date is {current_date}.
        3. Time in HH:MM format (e.g., 12:30). Always interpret times correctly based on the user's input.

        Output the result as JSON with these fields:
        - "title": (e.g., "Gym")
        - "date": (YYYY-MM-DD format)
        - "time": (HH:MM format)

        Only output a valid JSON object. Do not include explanations or additional text.

        Command: "{request.command}"
        """
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}]
        )

        parsed_data = response.choices[0].message.content.strip()
        print("GPT Parsed Data:", parsed_data)

        # Extract JSON from GPT response
        json_match = re.search(r"\{.*?\}", parsed_data, re.DOTALL)
        if not json_match:
            return {"error": "Failed to parse valid JSON from GPT response"}

        event_info = json.loads(json_match.group())

        # Validate parsed data
        if not all(key in event_info for key in ["title", "date", "time"]):
            return {"error": "Incomplete event information from GPT"}

        # Step 3: Convert the extracted time to UTC
        event_time_local = datetime.strptime(
            f"{event_info['date']} {event_info['time']}", "%Y-%m-%d %H:%M"
        )
        event_time_utc = user_tz.localize(event_time_local).astimezone(timezone("UTC"))

        start_time = event_time_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_time = (event_time_utc + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")  # Default to 2-hour duration

        # Step 4: Create the event in the calendar
        result = create_calendar_event(
            summary=event_info["title"],
            start_time=start_time,
            end_time=end_time,
            user_timezone=user_timezone
        )
        # Add event details to the logs
        print(f"Event Created: {result}, Start: {start_time}, End: {end_time}, Title: {event_info['title']}")
        return result

    except Exception as e:
        return {"error": f"Failed to interpret and create event: {str(e)}"}


@app.post("/interpret-command-date-time")
def interpret_command_date_time(request: CommandRequest):
    """
    Interpret date and time references.
    """
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = f"""
    Interpret the following command and extract date and time references. Output JSON with:
    - "date" in YYYY-MM-DD.
    - "time" in HH:MM format.

    Command: "{request.command}"
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}]
        )
        parsed_data = response.choices[0].message.content.strip()
        json_match = re.search(r"\{.*?\}", parsed_data, re.DOTALL)
        return json.loads(json_match.group())
    except Exception as e:
        return {"error": f"Failed to interpret command: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
