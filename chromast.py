import tkinter as tk
from tkinter import filedialog, messagebox
import os
import socket
import threading
import http.server
import socketserver
import pychromecast

# Global lista för högtalare
chromecasts = []
cast_dict = {}

# HTTP-server
PORT = 8000
Handler = http.server.SimpleHTTPRequestHandler

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = "127.0.0.1"
    finally:
        s.close()
    return IP

def start_http_server(directory):
    os.chdir(directory)
    httpd = socketserver.TCPServer(("", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

def cast_to_google_home(mp3_file_path, selected_device):
    directory = os.path.dirname(mp3_file_path)
    filename = os.path.basename(mp3_file_path)

    start_http_server(directory)
    ip = get_local_ip()
    mp3_url = f"http://{ip}:{PORT}/{filename}"

    cast = cast_dict.get(selected_device)
    if not cast:
        messagebox.showerror("Fel", "Vald högtalare hittades inte.")
        return

    cast.wait()
    mc = cast.media_controller
    mc.play_media(mp3_url, 'audio/mp3')
    mc.block_until_active()
    mc.play()
    messagebox.showinfo("Spelar upp", f"Spelar {filename} på {selected_device}.")

def välj_fil():
    filepath = filedialog.askopenfilename(filetypes=[("MP3 filer", "*.mp3")])
    if filepath:
        selected_device = device_var.get()
        if not selected_device:
            messagebox.showwarning("Ingen högtalare", "Välj en Google Home-högtalare först.")
            return
        cast_to_google_home(filepath, selected_device)

def hitta_enheter():
    global chromecasts, cast_dict
    chromecasts, browser = pychromecast.get_chromecasts()
    device_names = [cc.name for cc in chromecasts]
    cast_dict = {cc.name: cc for cc in chromecasts}
    return device_names

# GUI
root = tk.Tk()
root.title("MP3 till Google Home")

frame = tk.Frame(root)
frame.pack(padx=20, pady=20)

tk.Label(frame, text="Välj högtalare:").grid(row=0, column=0, sticky="w")

device_var = tk.StringVar()
device_dropdown = tk.OptionMenu(frame, device_var, [])
device_dropdown.grid(row=0, column=1)

def uppdatera_dropdown():
    enheter = hitta_enheter()
    menu = device_dropdown["menu"]
    menu.delete(0, "end")
    for device in enheter:
        menu.add_command(label=device, command=lambda value=device: device_var.set(value))
    if enheter:
        device_var.set(enheter[0])  # Välj första som standard

tk.Button(frame, text="Ladda högtalare", command=uppdatera_dropdown).grid(row=0, column=2, padx=10)

tk.Button(root, text="Välj MP3-fil att casta", command=välj_fil, height=3, width=30).pack(pady=10)

root.mainloop()
