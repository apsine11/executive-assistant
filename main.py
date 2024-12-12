import os
from openai import OpenAI
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pytz
from pytz.exceptions import UnknownTimeZoneError
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from datetime import datetime, timedelta
import requests
import json
import re

load_dotenv()

app = FastAPI()

# In-memory store for pending events
pending_events = {}

class CommandRequest(BaseModel):
    command: str

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_user_timezone():
    try:
        response = requests.get("https://ipinfo.io", timeout=5)
        data = response.json()
        return data.get("timezone", "UTC")
    except Exception as e:
        print(f"Time zone detection failed: {e}")
        return "UTC"

def build_service():
    creds = Credentials(
        token=os.getenv("GOOGLE_ACCESS_TOKEN"),
        refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET")
    )
    if creds.expired:
        creds.refresh(Request())
    return build('calendar', 'v3', credentials=creds)

def create_calendar_event(summary, start_time, end_time, user_timezone):
    try:
        service = build_service()
        event = {
            'summary': summary,
            'start': {'dateTime': start_time, 'timeZone': user_timezone},
            'end': {'dateTime': end_time, 'timeZone': user_timezone}
        }

        created_event = service.events().insert(calendarId='primary', body=event).execute()
        return {"success": True, "event_id": created_event.get("id")}
    except Exception as e:
        return {"success": False, "error": str(e)}

def classify_command(command: str, attempt: int = 1) -> str:
    prompt = f"""
    You are a helpful assistant. Classify the following command into one of these categories:
    - "meeting-summary"
    - "create-event"
    - "date-time-interpretation"
    - "confirmation" (for user responses like "Yes", "No", "That works", "Please schedule")

    Command: "{command}"
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}]
        )
        classification = response.choices[0].message.content.strip()
        if classification not in ["meeting-summary", "create-event", "date-time-interpretation", "confirmation"]:
            raise ValueError("Invalid classification returned by GPT.")
        return classification
    except Exception as e:
        print(f"GPT classification attempt {attempt} failed: {e}")
        if attempt == 1:
            return classify_command(command, attempt=2)
        else:
            return heuristic_classification(command)

def heuristic_classification(command: str) -> str:
    cmd_lower = command.lower()
    if any(keyword in cmd_lower for keyword in [
        "summarize", "spent my time", "spend my time",
        "what did my week look like", "last week", "this week", "next week", 
        "this month", "last month", "look like"
    ]):
        return "meeting-summary"
    elif any(keyword in cmd_lower for keyword in ["create", "schedule", "book", "set up", "block"]):
        return "create-event"
    elif cmd_lower in ["yes", "no", "sure", "okay", "that works", "please schedule", "ok", "no thanks", "not good"]:
        return "confirmation"
    else:
        return "date-time-interpretation"

@app.post("/parse-command")
def parse_with_classification(request: CommandRequest):
    try:
        classification = classify_command(request.command)
        print(f"Classified command '{request.command}' as '{classification}'")

        if classification == "meeting-summary":
            return meeting_summary_command(request)
        elif classification == "create-event":
            return interpret_and_create_event(request)
        elif classification == "confirmation":
            return handle_confirmation(request)
        elif classification == "date-time-interpretation":
            return interpret_command_date_time(request)
        else:
            return {"message": "I'm having trouble understanding your request. Could you try rephrasing it?"}

    except Exception as e:
        print(f"Error processing command: {e}")
        return {"error": "I'm having trouble understanding your request right now. Please try again later."}

def classify_user_response(response: str) -> str:
    """
    Classify user response into 'affirmation', 'rejection', or 'unclear'.
    """
    prompt = f"""
    You are a helpful assistant. Classify the user's response into one of three categories:
    - "affirmation" if the user indicates agreement or acceptance (e.g. "Yes", "That works", "Please schedule", "Sure", "Ok")
    - "rejection" if the user indicates disagreement or refusal (e.g. "No", "Not good", "Doesn't work", "No thanks")
    - "unclear" if it's not clear whether the user accepts or rejects.

    User response: "{response}"
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}]
        )
        classification = resp.choices[0].message.content.strip().lower()
        if classification not in ["affirmation", "rejection", "unclear"]:
            classification = "unclear"
        return classification
    except:
        # Fallback heuristic if GPT call fails
        resp_lower = response.lower()
        if any(word in resp_lower for word in ["yes", "sure", "ok", "that works", "please schedule"]):
            return "affirmation"
        elif any(word in resp_lower for word in ["no", "not good", "doesn't work", "nah", "no thanks"]):
            return "rejection"
        else:
            return "unclear"

def handle_confirmation(request: CommandRequest):
    user_id = "default_user"
    if user_id not in pending_events:
        return {"message": "There's nothing pending to confirm."}

    event_data = pending_events[user_id]
    classification = classify_user_response(request.command)

    if classification == "affirmation":
        # Schedule the event (either overlapping or the suggested time)
        result = create_calendar_event(
            summary=event_data["title"],
            start_time=event_data["start_time"],
            end_time=event_data["end_time"],
            user_timezone=event_data["user_timezone"]
        )
        del pending_events[user_id]
        if result.get("success"):
            local_time_str = convert_utc_to_local(event_data["start_time"], event_data["user_timezone"])
            return {"message": f"Scheduled '{event_data['title']}' on {local_time_str}"}
        else:
            return {"error": "Failed to schedule event."}
    elif classification == "rejection":
        # User rejects the suggestion, try another time
        return suggest_alternative_time(event_data)
    else:
        return {"message": "I didn't understand your response. Would you like to schedule anyway or find another time?"}

def suggest_alternative_time(event_data):
    user_id = "default_user"
    user_timezone = event_data["user_timezone"]
    user_tz = pytz.timezone(user_timezone)
    duration_minutes = event_data["duration_minutes"]
    service = build_service()

    increments_tried = event_data.get("increments_tried", 0)
    event_start_utc = datetime.strptime(event_data["start_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
    increment = timedelta(minutes=30)
    suggested_start = event_start_utc + increment*(increments_tried+1)

    while True:
        suggested_end = suggested_start + timedelta(minutes=duration_minutes)
        check_result = service.events().list(
            calendarId='primary',
            timeMin=suggested_start.isoformat(),
            timeMax=suggested_end.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        if not check_result.get('items', []):
            # Found a free slot
            local_suggested_str = convert_utc_to_local(suggested_start.strftime("%Y-%m-%dT%H:%M:%SZ"), user_timezone)
            event_data["start_time"] = suggested_start.strftime("%Y-%m-%dT%H:%M:%SZ")
            event_data["end_time"] = suggested_end.strftime("%Y-%m-%dT%H:%M:%SZ")
            event_data["increments_tried"] = increments_tried + 1
            pending_events[user_id] = event_data
            return {"message": f"Your requested time was booked. How about {local_suggested_str}?"}

        suggested_start += increment
        increments_tried += 1

        if increments_tried > 10:
            return {"message": "I'm having trouble finding a free slot. Please try a different time."}

def convert_utc_to_local(utc_str, user_timezone):
    utc_time = datetime.strptime(utc_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
    user_tz = pytz.timezone(user_timezone)
    local_time = utc_time.astimezone(user_tz)
    return local_time.strftime("%m/%d/%Y at %I:%M %p %Z")


@app.post("/meeting-summary-command")
def meeting_summary_command(request: CommandRequest):
    """
    Generate a meeting summary based on user input, handling both past and future requests.
    """
    user_timezone = get_user_timezone()
    user_tz = pytz.timezone(user_timezone)

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
    - "tomorrow" should mean one single day: tomorrow's date.
    - "yesterday" should mean one single day: yesterday's date.
    - "last month" should mean the full calendar month before today.
    - "this month" should mean the current month including today's date.
    - "next month" should mean the full upcoming calendar month, after the current month.

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
    try:
        user_timezone = get_user_timezone()
        try:
            user_tz = pytz.timezone(user_timezone)
        except UnknownTimeZoneError:
            user_tz = pytz.utc

        current_date = datetime.now(user_tz).strftime("%Y-%m-%d")

        prompt = f"""
        You are a smart assistant helping users schedule events. Interpret the following command and extract:
        1. Event title
        2. Date (YYYY-MM-DD) considering today's date is {current_date}
        3. Time (HH:MM)
        4. Duration in minutes (if mentioned, else 30)

        Only output a valid JSON object with fields:
        {{
          "title": "Event Title",
          "date": "YYYY-MM-DD",
          "time": "HH:MM",
          "duration_minutes": integer
        }}

        No extra text or comments.

        Command: "{request.command}"
        """

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}]
        )

        parsed_data = response.choices[0].message.content.strip()
        print("GPT Parsed Data:", parsed_data)

        json_match = re.search(r"\{.*?\}", parsed_data, re.DOTALL)
        if not json_match:
            return {"error": "Failed to parse valid JSON from GPT response"}

        event_info = json.loads(json_match.group())
        if not all(k in event_info for k in ["title", "date", "time", "duration_minutes"]):
            return {"error": "Incomplete event information from GPT"}

        event_time_local = datetime.strptime(f"{event_info['date']} {event_info['time']}", "%Y-%m-%d %H:%M")
        event_time_utc = user_tz.localize(event_time_local).astimezone(pytz.utc)

        duration_minutes = event_info["duration_minutes"]
        event_end_utc = event_time_utc + timedelta(minutes=duration_minutes)

        start_time_google = event_time_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_time_google = event_end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Check for conflicts
        service = build_service()
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_time_google,
            timeMax=end_time_google,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        overlapping_events = events_result.get('items', [])

        if overlapping_events:
            # Store event details and prompt user for confirmation
            user_id = "default_user"
            pending_events[user_id] = {
                "title": event_info["title"],
                "start_time": start_time_google,
                "end_time": end_time_google,
                "user_timezone": user_timezone,
                "duration_minutes": duration_minutes
            }
            return {"message": "There's an overlap with another event. Would you still like to schedule it?"}
        else:
            # No conflicts, schedule the event immediately
            result = create_calendar_event(
                summary=event_info["title"],
                start_time=start_time_google,
                end_time=end_time_google,
                user_timezone=user_timezone
            )
            return result

    except Exception as e:
        return {"error": f"Failed to interpret and create event: {str(e)}"}



@app.post("/interpret-command-date-time")
def interpret_command_date_time(request: CommandRequest):
    """
    Interpret date and time references.
    """
    current_date = datetime.now(pytz.utc).strftime("%Y-%m-%d")
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

