import tkinter as tk
from tkinter import scrolledtext
import requests
from pynput import keyboard
import json
import re
from datetime import datetime, timezone, timedelta
import speech_recognition as sr  # For voice input

class SpotlightInterface:
    def __init__(self):
        self.root = None
        self.entry = None
        self.output_text = None
        self.is_visible = False

        # Add a list of common suggestions (adjust as needed)
        self.suggestions = [
            "Summarize last week",
            "Summarize last month",
            "What did I spend most of my time on?",
            "Schedule a meeting tomorrow at 3 PM",
            "What is my availability next Tuesday?",
            "Summarize my meetings this week",
            "What does my next week look like?",
            "When am I free today?",
            "Create a new event next Monday at 10 AM",
            "Summarize yesterday's meetings"
        ]

        self.suggestion_box = None

    def create_interface(self):
        self.root = tk.Tk()
        self.root.title("Spotlight Search Interface")
        # Keep as a normal window for typing to work
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.9)
        self.root.configure(bg='black')

        # Intercept the "X" close action
        self.root.protocol("WM_DELETE_WINDOW", self.on_window_close)

        frame = tk.Frame(self.root, bg='black')
        frame.pack(padx=20, pady=20, fill=tk.X)

        # Voice Input Button
        voice_button = tk.Button(
            frame, text="🎤", command=self.start_voice_input,
            bg='black', fg='white', borderwidth=0, font=('Arial', 16)
        )
        voice_button.pack(side=tk.RIGHT)

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
        self.entry.pack(side=tk.LEFT, fill=tk.X)
        self.entry.bind('<Return>', self.send_command)
        self.entry.bind('<KeyRelease>', self.on_key_release)

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

        # Suggestion box (initially hidden)
        self.suggestion_box = tk.Listbox(
            self.root,
            width=50,
            bg='black',
            fg='white',
            font=('Arial', 12),
            highlightthickness=0,
            borderwidth=0
        )
        self.suggestion_box.bind('<<ListboxSelect>>', self.on_suggestion_select)

        self.root.bind('<FocusIn>', self.on_focus_in)
        self.center_window()

        # Hide window initially
        self.root.withdraw()

        return self.root
    
    def on_window_close(self):
        # Instead of destroying the window and ending the script,
        # just hide it. The application keeps running in the background.
        self.root.withdraw()
        self.is_visible = False    

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

    def on_key_release(self, event):
        typed = self.entry.get().strip().lower()
        if not typed:
            self.hide_suggestion_box()
            return

        # Filter suggestions
        filtered = [cmd for cmd in self.suggestions if typed in cmd.lower()]
        if filtered:
            self.suggestion_box.delete(0, tk.END)
            for suggestion in filtered:
                self.suggestion_box.insert(tk.END, suggestion)
            self.show_suggestion_box()
        else:
            self.hide_suggestion_box()

    def show_suggestion_box(self):
        # Position suggestion box below the entry widget
        self.suggestion_box.place(x=self.entry.winfo_x(), y=self.entry.winfo_y() + self.entry.winfo_height())
        self.suggestion_box.lift()
        # Don't move focus away from entry; user can still select by mouse

    def hide_suggestion_box(self):
        self.suggestion_box.place_forget()

    def on_suggestion_select(self, event):
        if not self.suggestion_box.curselection():
            return
        selected = self.suggestion_box.get(self.suggestion_box.curselection())
        self.entry.delete(0, tk.END)
        self.entry.insert(tk.END, selected)
        self.hide_suggestion_box()
        self.entry.focus_set()

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

        # Hide suggestions when user presses Enter
        self.hide_suggestion_box()

        try:
            response = requests.post("http://0.0.0.0:8000/parse-command", json={"command": command})
            result = response.json()
            print(result)

            if not self.output_text.winfo_ismapped():
                self.output_text.pack(pady=20, padx=20, fill=tk.BOTH, expand=True)

            self.output_text.config(state=tk.NORMAL)
            self.output_text.delete(1.0, tk.END)

            if "success" in result and result["success"]:
                self.output_text.insert(tk.END, f"Event created successfully: {result.get('event_id')}")
            elif "summary" in result:
                self.output_text.insert(tk.END, f"{result['summary']}")
            elif "message" in result:
                self.output_text.insert(tk.END, f"{result['message']}")
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
        self.output_text.update_idletasks()

        line_count = int(self.output_text.index('end').split('.')[0])
        text_height = line_count * 20
        current_width = self.root.winfo_width()
        new_height = max(75, min(500, text_height + 100))
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
            self.root.after(0, self.toggle_visibility)

        hotkey_combination = '<ctrl>+o'

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
        self.start_hotkey_listener()
        root.mainloop()

    def start_voice_input(self):
        r = sr.Recognizer()
        self.display_message("Listening... Please speak now.")

        with sr.Microphone() as source:
            audio = r.listen(source, phrase_time_limit=5)  # Adjust as needed

        try:
            command = r.recognize_google(audio)
            self.entry.delete(0, tk.END)
            self.entry.insert(tk.END, command)
            self.display_message(f"You said: {command}")
        except sr.UnknownValueError:
            self.display_message("Sorry, I didn't catch that.")
        except sr.RequestError as e:
            self.display_message("Could not request results from speech service.")

    def display_message(self, message):
        if not self.output_text.winfo_ismapped():
            self.output_text.pack(pady=20, padx=20, fill=tk.BOTH, expand=True)

        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete(1.0, tk.END)
        self.output_text.insert(tk.END, message)
        self.output_text.config(state=tk.DISABLED)
        self.auto_expand_window()


def main():
    app = SpotlightInterface()
    app.run()

if __name__ == "__main__":
    main()
