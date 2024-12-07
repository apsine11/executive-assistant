import tkinter as tk
from tkinter import scrolledtext
import requests
from pynput import keyboard
import threading

def send_command():
    command = entry.get()
    if command:
        try:
            response = requests.post("http://0.0.0.0:8000/meeting-summary-command", json={"command": command})
            result = response.json()
            print(result)

            # Check if output_text is already packed, if not, pack it
            if not output_text.winfo_ismapped():
                output_text.pack(pady=20, padx=10, fill=tk.BOTH, expand=True)

            # Configure output text to be editable
            output_text.config(state=tk.NORMAL)
            output_text.delete(1.0, tk.END)

            if "summary" in result:
                output_text.insert(tk.END, f"Summary:\n{result['summary']}")
            else:
                output_text.insert(tk.END, f"Error: {result.get('error', 'Unknown error')}")

            # Make output text read-only again
            output_text.config(state=tk.DISABLED)

            # Resize window to accommodate both input and output
            root.geometry("600x400")

        except Exception as e:
            # Check if output_text is already packed, if not, pack it
            if not output_text.winfo_ismapped():
                output_text.pack(pady=20, padx=10, fill=tk.BOTH, expand=True)

            # Configure output text to be editable
            output_text.config(state=tk.NORMAL)
            output_text.delete(1.0, tk.END)
            output_text.insert(tk.END, f"Failed to connect: {str(e)}")

            # Make output text read-only again
            output_text.config(state=tk.DISABLED)

            # Resize window to accommodate both input and output
            root.geometry("600x400")

def on_activate():
    # Always try to bring the window to front or show it
    root.deiconify()
    root.lift()
    root.focus_force()

    # Ensure entry is packed and focused
    if not entry.winfo_ismapped():
        entry.pack(fill=tk.BOTH, expand=True, padx=10, pady=20)
    entry.focus_set()
    entry.selection_range(0, tk.END)

def run_app():
    global root, entry, output_text
    root = tk.Tk()
    root.title("Spotlight Search Interface")
    root.geometry("600x75")  # Initial small size

    # Create a larger, more prominent entry widget
    entry = tk.Entry(root, width=50, font=('Arial', 14))
    entry.pack(fill=tk.BOTH, expand=True, padx=10, pady=20)

    entry.bind('<Return>', lambda event: send_command())

    # Create ScrolledText but don't pack it initially
    output_text = scrolledtext.ScrolledText(
        root,
        wrap=tk.WORD,
        width=50,
        height=10,
        state=tk.DISABLED  # Make text read-only
    )
    # Do NOT pack the output_text initially

    # Ensure the window can be properly hidden and shown
    root.protocol("WM_DELETE_WINDOW", root.withdraw)

    # Hide the window initially
    root.withdraw()

    return root

def start_hotkey_listener(root):
    def for_canonical(f):
        return lambda k: f(listener.canonical(k))

    def on_activate():
        root.after(0, root.deiconify)
        root.after(0, root.lift)
        root.after(0, root.focus_force)
        root.after(0, lambda: entry.pack(fill=tk.BOTH, expand=True, padx=10, pady=20) if not entry.winfo_ismapped() else None)
        root.after(0, lambda: entry.focus_set())
        root.after(0, lambda: entry.selection_range(0, tk.END))

    hotkey = keyboard.HotKey(
        keyboard.HotKey.parse('<ctrl>+o'),
        on_activate)

    def on_press(key):
        hotkey.press(listener.canonical(key))

    def on_release(key):
        hotkey.release(listener.canonical(key))

    with keyboard.Listener(
            on_press=on_press,
            on_release=on_release) as listener:
        listener.join()

def main():
    root = run_app()

    # Start hotkey listener in a separate thread
    hotkey_thread = threading.Thread(target=start_hotkey_listener, args=(root,), daemon=True)
    hotkey_thread.start()

    # Start the Tkinter event loop
    root.mainloop()

if __name__ == "__main__":
    main()