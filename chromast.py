import tkinter as tk
from tkinter import filedialog, messagebox
import os
import socket
import threading
import http.server
import socketserver
import pychromecast
import time

class ChromecastController:
    def __init__(self):
        self.chromecasts = []
        self.cast_dict = {}
        self.playlist = []
        self.current_song_index = 0
        self.httpd = None
        self.PORT = 8000
        self.Handler = http.server.SimpleHTTPRequestHandler
        self.server_directory = None
        self.gui = None

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            IP = s.getsockname()[0]
            s.close()
            return IP
        except Exception:
            return "127.0.0.1"

    def start_http_server(self, directory):
        if self.httpd and self.server_directory == directory:
            return True
        elif self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
                time.sleep(1)
            except Exception:
                pass
            self.httpd = None

        os.chdir(directory)
        self.server_directory = directory
        max_attempts = 10
        current_port = self.PORT
        for attempt in range(max_attempts):
            try:
                self.httpd = socketserver.TCPServer(("", current_port), self.Handler)
                self.PORT = current_port
                threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
                return True
            except OSError as e:
                if "Address already in use" in str(e):
                    current_port += 1
                else:
                    self.httpd = None
                    return False
        self.httpd = None
        return False

    def cast_to_google_home(self, mp3_file_path, selected_device):
        directory = os.path.dirname(mp3_file_path)
        filename = os.path.basename(mp3_file_path)

        if not self.start_http_server(directory):
            return

        ip = self.get_local_ip()
        mp3_url = f"http://{ip}:{self.PORT}/{filename}"

        cast = self.cast_dict.get(selected_device)
        if not cast:
            print("Vald högtalare hittades inte.")
            return

        try:
            cast.wait()
            mc = cast.media_controller
            mc.play_media(mp3_url, 'audio/mp3')
            mc.block_until_active()
            try:
                mc.play()
            except pychromecast.error.RequestFailed as e:
                print(f"Fel vid uppspelning: {e}")
            self.update_volume_label(cast)
            self.update_playlist_display()
            threading.Thread(target=self.check_if_song_finished, args=(cast, selected_device), daemon=True).start()
        except pychromecast.error.ChromecastConnectionError:
            print("Chromecast-enheten är inte tillgänglig.")

    def check_if_song_finished(self, cast, selected_device):
        try:
            mc = cast.media_controller
            while True:
                if not mc.status or mc.status.player_state not in ['PLAYING', 'BUFFERING']:
                    break
                time.sleep(1)
            # Gå till nästa låt om det finns
            if self.current_song_index < len(self.playlist) - 1:
                self.current_song_index += 1
                next_song = self.playlist[self.current_song_index]
                self.cast_to_google_home(next_song, selected_device)
            else:
                print("Spellistan är klar")
        except pychromecast.error.ChromecastConnectionError:
            print("Chromecast-enheten kopplades bort under uppspelning.")

    def adjust_volume(self, selected_device, volume):
        cast = self.cast_dict.get(selected_device)
        if not cast:
            return
        try:
            cast.wait()
            new_volume = volume / 100.0
            cast.set_volume(new_volume)
            self.update_volume_label(cast)
        except pychromecast.error.ChromecastConnectionError:
            pass

    def update_volume_label(self, cast):
        try:
            volume = int(cast.status.volume_level * 100)
            self.gui.volume_label.config(text=f"Volym: {volume}%")
            self.gui.volume_slider.set(volume)
        except:
            self.gui.volume_label.config(text="Volym: Okänd")
            self.gui.volume_slider.set(50)

    def pause_playback(self, selected_device):
        cast = self.cast_dict.get(selected_device)
        if not cast:
            print("Vald högtalare hittades inte.")
            return
        try:
            cast.wait()
            mc = cast.media_controller
            if mc.status and mc.status.player_state == 'PLAYING':
                mc.pause()
            else:
                max_retries = 3
                retries = 0
                while retries < max_retries:
                    try:
                        mc.play()
                        break
                    except pychromecast.error.RequestFailed as e:
                        retries += 1
                        print(f"Fel vid uppspelning (retry {retries}/{max_retries}): {e}")
                        time.sleep(1)
                if retries == max_retries:
                    print("Kunde inte spela upp media efter flera försök.")
        except pychromecast.error.ChromecastConnectionError:
            print("Chromecast-enheten är inte tillgänglig.")

    def stop_playback(self, selected_device):
        cast = self.cast_dict.get(selected_device)
        if not cast:
            print("Vald högtalare hittades inte.")
            return
        try:
            cast.wait()
            mc = cast.media_controller
            mc.stop()
        except pychromecast.error.ChromecastConnectionError:
            print("Chromecast-enheten är inte tillgänglig.")

    def hitta_enheter(self):
        try:
            self.chromecasts, browser = pychromecast.get_chromecasts()
            device_names = [cc.name for cc in self.chromecasts]
            self.cast_dict = {cc.name: cc for cc in self.chromecasts}
            return device_names
        except pychromecast.error.ChromecastConnectionError:
            print("Kunde inte hitta några Chromecast-enheter.")
            return []

    def update_playlist_display(self):
        self.gui.playlist_listbox.delete(0, tk.END)
        for i, song in enumerate(self.playlist):
            self.gui.playlist_listbox.insert(tk.END, os.path.basename(song))
            if i == self.current_song_index:
                self.gui.playlist_listbox.itemconfig(i, {'fg': 'blue'})

    def set_gui(self, gui):
        self.gui = gui

class GUI:
    def __init__(self, root):
        self.root = root
        self.chromecast_controller = ChromecastController()
        self.chromecast_controller.set_gui(self)
        self.device_var = tk.StringVar()
        self.create_widgets()

    def create_widgets(self):
        frame = tk.Frame(self.root)
        frame.pack(padx=20, pady=20)

        tk.Label(frame, text="Välj högtalare:").grid(row=0, column=0, sticky="w")

        device_dropdown = tk.OptionMenu(frame, self.device_var, [])
        device_dropdown.grid(row=0, column=1)

        def uppdatera_dropdown():
            enheter = self.chromecast_controller.hitta_enheter()
            menu = device_dropdown["menu"]
            menu.delete(0, "end")
            for device in enheter:
                menu.add_command(label=device, command=lambda value=device: self.device_var.set(value))

        tk.Button(frame, text="Välj Chromecast", command=uppdatera_dropdown).grid(row=0, column=2, padx=10)

        tk.Button(self.root, text="Välj MP3-filer att casta", command=self.välj_filer, height=3, width=30).pack(pady=10)

        # Volymreglage HORIZONTAL
        volume_frame = tk.Frame(self.root)
        volume_frame.pack(pady=5)
        tk.Label(volume_frame, text="Volym:").pack(side=tk.LEFT)
        self.volume_slider = tk.Scale(volume_frame, from_=0, to=100, orient=tk.HORIZONTAL, length=200,
                                command=lambda value: self.chromecast_controller.adjust_volume(self.device_var.get(), float(value)))
        self.volume_slider.set(50)
        self.volume_slider.pack(side=tk.LEFT, padx=5)

        self.volume_label = tk.Label(self.root, text="Volym: Okänd")
        self.volume_label.pack(pady=5)

        control_frame = tk.Frame(self.root)
        control_frame.pack(pady=5)
        tk.Button(control_frame, text="Paus/Spela", command=lambda: self.chromecast_controller.pause_playback(self.device_var.get())).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="Stopp", command=lambda: self.chromecast_controller.stop_playback(self.device_var.get())).pack(side=tk.LEFT, padx=5)

        playlist_frame = tk.Frame(self.root)
        playlist_frame.pack(pady=10, fill=tk.BOTH, expand=True)
        tk.Label(playlist_frame, text="Spellista:").pack()
        self.playlist_listbox = tk.Listbox(playlist_frame, width=50, height=10)
        self.playlist_listbox.pack(pady=5)

    def välj_filer(self):
        filepaths = filedialog.askopenfilenames(filetypes=[("MP3 filer", "*.mp3")])
        if filepaths:
            selected_device = self.device_var.get()
            if not selected_device:
                messagebox.showwarning("Ingen högtalare", "Välj en Google Home-högtalare först.")
                return
            self.chromecast_controller.playlist = list(filepaths)
            self.chromecast_controller.current_song_index = 0
            self.chromecast_controller.update_playlist_display()
            self.chromecast_controller.cast_to_google_home(self.chromecast_controller.playlist[0], selected_device)

def main():
    root = tk.Tk()
    root.title("MP3 till Google Home")
    gui = GUI(root)

    def on_closing():
        if gui.chromecast_controller.httpd:
            try:
                gui.chromecast_controller.httpd.shutdown()
                gui.chromecast_controller.httpd.server_close()
                time.sleep(1)
            except Exception as e:
                print(f"Kunde inte stänga servern: {e}")
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
