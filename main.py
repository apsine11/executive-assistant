import os
from openai import OpenAI
from fastapi import FastAPI, Query
from pydantic import BaseModel
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from datetime import datetime, timezone, timedelta
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


from datetime import datetime, timedelta

@app.post("/meeting-summary-command")
def meeting_summary_command(request: CommandRequest):
    """
    Generate a meeting summary based on user input (command).
    """
    # Get the current date
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Prepare the GPT prompt
    prompt = f"""
    You are a helpful assistant. Today's date is {current_date}.
    Parse the following command and identify the desired date range for summarizing meetings.

    Command: "{request.command}"

    Return a JSON object with fields: "start_date" and "end_date" in YYYY-MM-DD format. 
    If the user doesn't specify a range, you must calculate the dates based on the command and return them in the JSON format. 
    Ensure that the output is a valid JSON object without any additional text or explanations. ONLY INCLUDE THE JSON OUTPUT.

    Example Outputs:
    - For "Summarize my meetings for last week": 
        {{
            "start_date": "2024-12-02",
            "end_date": "2024-12-08"
        }}
    - For "Generate a summary for November": 
        {{
            "start_date": "2024-11-01",
            "end_date": "2024-11-30"
        }}
    """

    try:
        # Call GPT-4 to parse the command
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt}
            ]
        )

        # Parse GPT response for the date range
        parsed_data = response.choices[0].message.content
        print(f"GPT Parsed Data: {parsed_data}")  # Debugging

        # Clean the output to remove formatting
        cleaned_data = re.sub(r'```json\n|\n```', '', parsed_data).strip()
        print(f"cleaned data: {cleaned_data}")

        # Attempt to convert cleaned response to a Python dictionary
        try:
            date_range = json.loads(cleaned_data)
        except json.JSONDecodeError:
            return {"error": "Invalid JSON response from GPT. Please ensure the command is clear."}

        start_date = date_range.get("start_date")
        end_date = date_range.get("end_date")

        # Fallback: Calculate ranges programmatically if needed
        if not start_date or not end_date:
            now = datetime.now(timezone.utc)

            if "last week" in request.command.lower():
                start_date = (now - timedelta(days=now.weekday() + 7)).strftime("%Y-%m-%d")
                end_date = (now - timedelta(days=now.weekday() + 1)).strftime("%Y-%m-%d")
            elif "this week" in request.command.lower():
                start_date = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
                end_date = (now + timedelta(days=6 - now.weekday())).strftime("%Y-%m-%d")
            elif "this month" in request.command.lower():
                start_date = now.replace(day=1).strftime("%Y-%m-%d")
                end_date = (now.replace(day=1) + timedelta(days=31)).replace(day=1) - timedelta(days=1)
                end_date = end_date.strftime("%Y-%m-%d")
            elif "last month" in request.command.lower():
                first_day_of_this_month = now.replace(day=1)
                start_date = (first_day_of_this_month - timedelta(days=1)).replace(day=1).strftime("%Y-%m-%d")
                end_date = (first_day_of_this_month - timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                # Default to current week
                start_date = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
                end_date = (now + timedelta(days=6 - now.weekday())).strftime("%Y-%m-%d")

        # Check if start_date and end_date are still empty
        if not start_date or not end_date:
            return {"error": "Unable to determine date range from command."}

        # Fetch meetings within the calculated date range
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

        events_result = service.events().list(
            calendarId='primary',
            timeMin=f"{start_date}T00:00:00Z",
            timeMax=f"{end_date}T23:59:59Z",
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        if not events:
            return {"message": f"No meetings found between {start_date} and {end_date}"}

        # Format meetings for GPT
        meetings_text = "\n".join([
            f"- Title: {event.get('summary', 'No Title')}, Start: {event['start'].get('dateTime', event['start'].get('date'))}, "
            f"End: {event['end'].get('dateTime', event['end'].get('date'))}, Attendees: {', '.join([a.get('email', 'Unknown') for a in event.get('attendees', [])])}"
            for event in events
        ])

        print(f"meetings text: {meetings_text}")

        # Use GPT to summarize the meetings
        summary_prompt = f"""
        You are an assistant that helps users understand their meeting schedules. Here is a list of meetings for the range {start_date} to {end_date}:

        Summarize the following meetings in a concise format, focusing on total time spent, average duration, types of meetings, and key suggestions for improving efficiency.

        {meetings_text}

        Summarize the following:
        - Total time spent in all meetings
        - Total time spent in each meeting.
        - Average meeting duration.
        - Count of meetings by type (e.g., client, internal).
        - Suggestions for improving meeting efficiency.
        """

        summary_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": summary_prompt}
            ]
        )

        # Parse GPT summary
        gpt_summary = summary_response.choices[0].message.content
        return {
            "start_date": start_date,
            "end_date": end_date,
            "summary": gpt_summary
        }

    except Exception as e:
        return {"error": f"Failed to generate meeting summary: {str(e)}"}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

