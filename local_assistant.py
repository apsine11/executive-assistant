import tkinter as tk
from tkinter import scrolledtext
import requests
from pynput import keyboard
import threading
import json
import re
from datetime import datetime, timezone, timedelta

class SpotlightInterface:
    def __init__(self):
        self.root = None
        self.entry = None
        self.output_text = None
        self.is_visible = False

    def create_interface(self):
        self.root = tk.Tk()
        self.root.title("Spotlight Search Interface")
        # Keep as a normal window for typing to work
        # self.root.overrideredirect(True)  # Not used, to allow typing

        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.9)
        self.root.configure(bg='black')

        frame = tk.Frame(self.root, bg='black')
        frame.pack(padx=20, pady=20, fill=tk.X)

        self.entry = tk.Entry(
            frame, 
            width=50, 
            font=('Arial', 16), 
            bg='black', 
            fg='white', 
            insertbackground='white',
            borderwidth=0,
            highlightthickness=0
        )
        self.entry.pack(fill=tk.X)
        self.entry.bind('<Return>', self.send_command)

        self.output_text = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            width=50,
            height=10,
            state=tk.DISABLED,
            bg='black',
            fg='white',
            insertbackground='white'
        )

        self.root.bind('<FocusIn>', self.on_focus_in)

        self.center_window()

        # Hide window initially
        self.root.withdraw()

        return self.root

    def on_focus_in(self, event=None):
        # Ensure entry gets focus
        self.entry.focus_set()

    def center_window(self):
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = 600
        window_height = 75
        x = (screen_width // 2) - (window_width // 2)
        y = screen_height // 4
        self.root.geometry(f'{window_width}x{window_height}+{x}+{y}')

    def classify_command(command: str) -> str:
        """
        Classify the user command into an appropriate endpoint using GPT.
        """
        prompt = f"""
        You are a helpful assistant that routes user commands to the correct API endpoint. 
        Here are the available endpoints:
        1. "/meeting-summary-command": Used for commands related to summarizing meeting schedules (e.g., "Summarize last week", "What did my week look like?").
        2. "/interpret-and-create-event": Used for commands related to scheduling or creating events (e.g., "Schedule a gym session tomorrow at 5 PM").
        3. "/interpret-command-date-time": Used for commands related to time or availability queries (e.g., "When am I free tomorrow?", "Check my availability next week").

        Based on the command below, classify it into one of these endpoints. Only return the endpoint name as your response.

        Command: "{command}"
        """
        try:
            # Call GPT to classify the command
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": prompt}]
            )

            endpoint = response.choices[0].message.content.strip()
            if endpoint not in ["/meeting-summary-command", "/interpret-and-create-event", "/interpret-command-date-time"]:
                raise ValueError(f"Invalid endpoint returned: {endpoint}")

            return endpoint
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to classify command: {str(e)}")


    def send_command(self, event=None):
        command = self.entry.get().strip()
        if not command:
            if not self.output_text.winfo_ismapped():
                self.output_text.pack(pady=20, padx=20, fill=tk.BOTH, expand=True)

            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete(1.0, tk.END)
            self.output_text.insert(tk.END, "Please enter a command.")
            self.output_text.config(state=tk.DISABLED)
            self.auto_expand_window()
            return

        try:
            # Always call the central endpoint
            response = requests.post(f"http://0.0.0.0:8000/parse-command", json={"command": command})
            result = response.json()
            print(result)

            if not self.output_text.winfo_ismapped():
                self.output_text.pack(pady=20, padx=20, fill=tk.BOTH, expand=True)

            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete(1.0, tk.END)

            if "success" in result and result["success"]:
                self.output_text.insert(tk.END, f"Event created successfully: {result.get('event_id')}")
            elif "summary" in result:
                self.output_text.insert(tk.END, f"Summary:\n{result['summary']}")
            elif "error" in result:
                self.output_text.insert(tk.END, f"Error: {result['error']}")
            else:
                self.output_text.insert(tk.END, f"Response: {result}")

            self.output_text.config(state=tk.DISABLED)
            self.auto_expand_window()

        except Exception as e:
            if not self.output_text.winfo_ismapped():
                self.output_text.pack(pady=20, padx=20, fill=tk.BOTH, expand=True)

            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete(1.0, tk.END)
            self.output_text.insert(tk.END, f"Failed to connect: {str(e)}")
            self.output_text.config(state=tk.DISABLED)
            self.auto_expand_window()

    def auto_expand_window(self):
        """
        Automatically expand the window size based on the content in the output_text widget.
        """
        # Force update the widget to calculate its new size
        self.output_text.update_idletasks()

        # Get the updated height of the output_text content
        line_count = int(self.output_text.index('end').split('.')[0])  # Line count in the widget
        text_height = line_count * 20  # Approximate pixel height for each line

        # Get the current window width and calculate new height
        current_width = self.root.winfo_width()
        new_height = max(75, min(500, text_height + 100))  # Minimum 75, maximum 500

        # Update the main window size
        self.root.geometry(f"{current_width}x{new_height}")
        self.root.update()




    def toggle_visibility(self):
        if self.is_visible:
            # Hide window
            self.root.withdraw()
            self.is_visible = False
        else:
            # Show window
            self.root.deiconify()
            self.root.lift()
            self.root.update_idletasks()
            self.root.focus_force()
            self.entry.focus_set()
            self.entry.selection_range(0, tk.END)
            self.is_visible = True

    def start_hotkey_listener(self):
        def on_activate():
            # Toggle visibility on the main thread
            self.root.after(0, self.toggle_visibility)

        hotkey_combination = '<ctrl>+o'  # Change to desired hotkey if needed

        hotkey = keyboard.HotKey(
            keyboard.HotKey.parse(hotkey_combination),
            on_activate
        )

        def on_press(key):
            try:
                hotkey.press(listener.canonical(key))
            except:
                pass

        def on_release(key):
            try:
                hotkey.release(listener.canonical(key))
            except:
                pass

        listener = keyboard.Listener(
            on_press=on_press,
            on_release=on_release,
            suppress=False
        )
        
        listener.start()

    def run(self):
        root = self.create_interface()

        # Start hotkey listener in a separate thread
        # Actually, pynput's listener doesn't block mainloop, so no need for separate thread
        self.start_hotkey_listener()

        root.mainloop()

def main():
    app = SpotlightInterface()
    app.run()

if __name__ == "__main__":
    main()
