import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import socket
import threading
import http.server
import socketserver
import pychromecast
import time
import logging
import urllib.parse # För säker URL-hantering och kodning

# Loggning - Endast till fil
logging.basicConfig(
    level=logging.INFO, # Ändra till logging.DEBUG för mer detaljerad loggning
    format='%(asctime)s - %(levelname)s - %(threadName)s - %(message)s', # Lade till trådnamn
    handlers=[
        logging.FileHandler('mp3_to_chromecast.log', encoding='utf-8')
    ]
)

# Hjälptext
help_text = """
MP3 till Chromecast – Användarmanual

Detta program låter dig spela upp MP3-filer från din dator på din Google Chromecast-enhet.

**Steg:**
1.  **Välj Chromecast:** Vid start söks enheter. Välj din högtalare. Klicka "Uppdatera enheter" vid behov.
2.  **Lägg till MP3-filer:** Klicka "Lägg till MP3-filer". Första låten spelas automatiskt. Max 100 filer.
3.  **Spellista:** Dubbelklicka en låt för att spela den. Aktiv låt är blå.
4.  **Kontroller:**
    *   **Volym:** Justera med reglaget.
    *   **Paus/Spela:** Pausa eller återuppta.
    *   **Stopp:** Stoppa uppspelningen.
    *   **Rensa spellista:** Tar bort alla låtar.
5.  **Status:** Visar aktuell aktivitet.
6.  **Nu spelas:** Visar aktuell låt.

**Tekniskt:**
Programmet startar en lokal HTTP-server för att kunna strömma filerna. Din dator måste vara på och i samma nätverk. Brandväggen får inte blockera port 8000 (eller nästa lediga).

**Felsökning:**
*   **Enheter hittas inte:** Kontrollera nätverk, Wi-Fi, brandvägg. Prova "Uppdatera enheter".
*   **Låten spelas inte:** Kontrollera statusfältet, filformat, nätverk. Se 'mp3_to_chromecast.log'.
*   **GUI fryser:** Bör inte hända. Rapportera felet om det sker till clas.klasson@gmail.com.

**Avsluta:** Stäng fönstret. HTTP-servern stängs ner.
"""

# Globala variabler
chromecasts = []
cast_dict = {}
playlist = []
current_song_index = 0
httpd = None
PORT = 8000
server_directory = None
volume_label = None
volume_slider = None
status_label = None
now_playing_label = None
current_cast = None
manual_playback_control = False


class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        try:
            decoded_path = urllib.parse.unquote(path)
            base_dir = server_directory or os.getcwd()
            requested_file_path = os.path.join(base_dir, decoded_path.lstrip('/'))
            real_base_dir = os.path.realpath(base_dir)
            real_requested_path = os.path.realpath(requested_file_path)

            if not real_requested_path.startswith(real_base_dir):
                logging.warning(f"HTTP Server: Försök till otillåten sökväg: {path} -> {real_requested_path}")
                return None
            logging.debug(f"HTTP Server: Serverar fil: {real_requested_path}")
            return real_requested_path
        except Exception as e:
            logging.error(f"HTTP Server: Fel vid översättning av sökväg {path}: {e}", exc_info=True)
            return None

def get_local_ip():
    logging.debug("Hämtar lokal IP")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        IP = s.getsockname()[0]
    except Exception as e:
        logging.error(f"Kunde inte hämta lokal IP: {e}", exc_info=True)
        IP = "127.0.0.1"
        root.after(0, lambda: set_status("Varning: Kunde inte hämta lokal IP. Använder 127.0.0.1."))
    finally:
        s.close()
    logging.debug(f"Hämtade IP {IP}")
    return IP

def start_http_server(directory):
    global httpd, server_directory, PORT
    logging.debug(f"Försöker starta HTTP-server för katalog: {directory}")
    abs_directory = os.path.abspath(directory)
    abs_server_directory = os.path.abspath(server_directory) if server_directory else None

    if httpd and abs_server_directory == abs_directory:
        logging.debug("HTTP-server körs redan för samma katalog.")
        return True
    if httpd:
        logging.debug("Stänger befintlig HTTP-server...")
        try:
            httpd.shutdown()
            httpd.server_close()
            time.sleep(0.1)
            logging.debug("Befintlig server stängd.")
        except Exception as e:
            logging.error(f"Kunde inte stänga befintlig HTTP-server: {e}", exc_info=True)
        httpd = None
        server_directory = None

    server_directory = abs_directory
    max_attempts = 20
    current_port = PORT
    for attempt in range(max_attempts):
        try:
            server = socketserver.ThreadingTCPServer(("", current_port), CustomHandler)
            httpd = server
            PORT = current_port
            threading.Thread(target=httpd.serve_forever, daemon=True, name="HTTPServerThread").start()
            logging.info(f"HTTP-server start initierad på port {PORT}")
            time.sleep(0.05)
            return True
        except OSError as e:
            logging.warning(f"Port {current_port} misslyckades: {e}. Försöker nästa port.")
            current_port += 1
            if current_port > 65535: current_port = 8000
    logging.error(f"Kunde inte starta HTTP-server efter {max_attempts} försök.")
    root.after(0, lambda: set_status("Kunde inte starta HTTP-server. Kontrollera brandvägg/andra program."))
    httpd = None
    server_directory = None
    return False

def run_in_thread(target_func, *args, callback_success=None, callback_failure=None):
    """Kör en funktion i en separat daemon-tråd och hanterar callbacks."""
    def wrapper():
        thread_name = threading.current_thread().name
        logging.debug(f"Tråd '{thread_name}' startad för: {target_func.__name__}")
        try:
            result = target_func(*args)
            logging.debug(f"Tråd '{thread_name}' för {target_func.__name__} slutförd med resultat: {result is not None}")
            if callback_success:
                root.after(0, lambda: callback_success(result))
        except Exception as e:
            logging.error(f"Fel i trådad funktion {target_func.__name__} (tråd '{thread_name}'): {e}", exc_info=True)
            if callback_failure:
                root.after(0, lambda: callback_failure(e))
        logging.debug(f"Tråd '{thread_name}' för {target_func.__name__} avslutas.")

    thread = threading.Thread(target=wrapper, daemon=True, name=f"{target_func.__name__}Thread")
    thread.start()
    return thread

# --- Bakgrundsfunktioner för Chromecast (körs i trådar) ---

def _bg_cast_to_google_home(mp3_file_path, selected_device_name):
    global current_cast, manual_playback_control
    logging.debug(f"BG: Förbereder cast av {mp3_file_path} till {selected_device_name}")
    cast = cast_dict.get(selected_device_name)
    if not cast:
        logging.error(f"BG: Högtalare '{selected_device_name}' hittades inte.")
        root.after(0, lambda: set_status(f"Fel: Högtalare '{selected_device_name}' hittades inte."))
        root.after(0, uppdatera_dropdown_action) # Försök uppdatera
        return False

    directory = os.path.dirname(mp3_file_path)
    filename = os.path.basename(mp3_file_path)
    abs_directory = os.path.abspath(directory)
    abs_server_directory = os.path.abspath(server_directory) if server_directory else None

    if not httpd or abs_server_directory != abs_directory:
         logging.error(f"BG: HTTP-servern felkonfigurerad ('{abs_server_directory}' vs '{abs_directory}').")
         root.after(0, lambda: set_status("Fel: HTTP-servern felkonfigurerad."))
         return False

    ip = get_local_ip()
    mp3_url = f"http://{ip}:{PORT}/{urllib.parse.quote(filename)}"
    logging.info(f"BG: Försöker spela URL: {mp3_url}")

    cast.wait() # Blockerande
    if current_cast and current_cast != cast:
        logging.debug("BG: Byter aktiv cast-enhet.")
    current_cast = cast
    manual_playback_control = False
    mc = cast.media_controller
    root.after(0, lambda: set_status(f"Laddar: {filename}"))
    mc.play_media(mp3_url, 'audio/mp3')

    timeout_start = time.time()
    while mc.status is None or mc.status.player_state not in ['PLAYING', 'BUFFERING', 'PAUSED']:
        if time.time() - timeout_start > 20:
            logging.warning(f"BG: Timeout vid laddning av {filename}")
            root.after(0, lambda: set_status(f"Fel: Timeout vid uppspelning av {filename}."))
            current_cast = None
            return False
        if not cast.status or not cast.status.is_connected:
            logging.warning("BG: Cast kopplades ifrån under laddning.")
            root.after(0, lambda: set_status("Chromecast kopplades ifrån."))
            current_cast = None
            return False
        time.sleep(0.5)

    if mc.status.player_state == 'PAUSED': mc.play()
    root.after(0, lambda: set_status(f"Spelar: {filename}"))
    root.after(0, lambda: now_playing_label.config(text=f"Nu spelas: {filename}"))
    run_in_thread(update_volume_label_bg, cast) # Uppdatera volym i tråd
    root.after(0, update_playlist_display_gui)
    run_in_thread(_bg_check_if_song_finished, cast, selected_device_name)
    logging.info(f"BG: Uppspelning av {filename} startad.")
    return True


def _bg_check_if_song_finished(cast, selected_device_name):
    global current_song_index, current_cast, manual_playback_control
    logging.debug(f"BG_CHECK: Startar för {selected_device_name}")
    mc = cast.media_controller
    while cast.status and cast.status.is_connected and current_cast == cast and \
          mc.status and mc.status.player_state in ['PLAYING', 'BUFFERING']:
        time.sleep(3)
        if manual_playback_control:
            logging.debug("BG_CHECK: Manuell kontroll, avslutar.")
            return
        if not cast.status or not cast.status.is_connected:
            logging.warning("BG_CHECK: Cast kopplades ifrån.")
            root.after(0, lambda: set_status("Chromecast kopplades ifrån."))
            current_cast = None; root.after(0, lambda: now_playing_label.config(text="Nu spelas: Ingen låt"))
            return
        if current_cast != cast:
            logging.debug("BG_CHECK: Current cast ändrad, avslutar.")
            return

    logging.debug(f"BG_CHECK: Loop avslutad. State: {mc.status.player_state if mc.status else 'None'}.")
    if manual_playback_control or current_cast != cast: return

    if cast.status and cast.status.is_connected and mc.status and mc.status.player_state == 'IDLE':
        if playlist and current_song_index < len(playlist) - 1:
            logging.info("BG_CHECK: Nästa låt.")
            current_song_index += 1
            next_song = playlist[current_song_index]
            root.after(0, lambda: run_in_thread(_bg_cast_to_google_home, next_song, selected_device_name))
        elif playlist and current_song_index >= len(playlist) - 1:
            logging.info("BG_CHECK: Spellistan klar.")
            root.after(0, lambda: set_status("Spellistan är klar."))
            root.after(0, lambda: now_playing_label.config(text="Nu spelas: Ingen låt"))
            root.after(0, update_playlist_display_gui) # Rensa markering
            current_cast = None


def _bg_adjust_volume(selected_device_name, volume_float):
    cast = cast_dict.get(selected_device_name)
    if not cast:
        logging.error(f"BG_VOL: Högtalare '{selected_device_name}' hittades inte.")
        root.after(0, lambda: set_status("Vald högtalare hittades inte."))
        return
    cast.wait()
    new_volume = max(0.0, min(1.0, volume_float / 100.0))
    cast.set_volume(new_volume)
    logging.info(f"BG_VOL: Volym satt till {int(new_volume*100)}% på {selected_device_name}.")
    # Volymen uppdateras visuellt via statuslyssnare eller manuellt anrop av update_volume_label_bg
    run_in_thread(update_volume_label_bg, cast)


def update_volume_label_bg(cast_obj):
    if not cast_obj or not cast_obj.status: return # Om cast_obj är None eller saknar status
    if cast_obj.status.volume_level is not None:
        volume = int(cast_obj.status.volume_level * 100)
        root.after(0, lambda: volume_label.config(text=f"Volym: {volume}%"))
        root.after(0, lambda: volume_slider.set(volume))
    else:
        root.after(0, lambda: volume_label.config(text="Volym: Okänd"))


def _bg_pause_playback(selected_device_name):
    global manual_playback_control
    cast = cast_dict.get(selected_device_name)
    if not cast: return
    cast.wait()
    mc = cast.media_controller
    if mc.status and mc.status.player_state == 'PLAYING':
        mc.pause(); manual_playback_control = True
        root.after(0, lambda: set_status("Uppspelning pausad."))
    elif mc.status and mc.status.player_state == 'PAUSED':
        mc.play(); manual_playback_control = False # Spelar nu, automatisk nästa låt kan ske
        root.after(0, lambda: set_status("Uppspelning återupptagen."))


def _bg_stop_playback(selected_device_name):
    global manual_playback_control, current_cast
    cast = cast_dict.get(selected_device_name)
    if not cast: return
    cast.wait()
    mc = cast.media_controller
    mc.stop(); manual_playback_control = True
    root.after(0, lambda: set_status("Uppspelning stoppad."))
    root.after(0, lambda: now_playing_label.config(text="Nu spelas: Ingen låt"))
    if current_cast == cast: current_cast = None


def _bg_hitta_enheter():
    global chromecasts, cast_dict
    logging.debug("BG_SCAN: Söker Chromecast-enheter")
    try:
        found_casts, _ = pychromecast.get_chromecasts()
        cast_dict = {cc.name: cc for cc in found_casts}
        chromecasts = found_casts # Uppdatera globala listan med cast-objekt
        device_names = [cc.name for cc in found_casts]
        logging.info(f"BG_SCAN: Hittade {len(device_names)} enheter.")
        return device_names
    except pychromecast.error.ChromecastConnectionError as e:
        logging.error(f"BG_SCAN: Kunde inte hitta Chromecast-enheter: {e}", exc_info=True)
        return [] # Returnera tom lista vid fel
    except Exception as e:
         logging.error(f"BG_SCAN: Oväntat fel vid enhetssökning: {e}", exc_info=True)
         return []


# --- GUI Event Handlers (körs i GUI-tråden, startar bakgrundstrådar) ---

def välj_filer_action():
    filepaths = filedialog.askopenfilenames(filetypes=[("MP3 filer", "*.mp3")])
    if not filepaths: return
    selected_device = device_var.get()
    if not selected_device:
        root.after(0, lambda: set_status("Välj en Chromecast-högtalare först."))
        return

    global playlist, current_song_index
    playlist = list(filepaths)[:100]
    current_song_index = 0
    root.after(0, update_playlist_display_gui)
    root.after(0, lambda: set_status(f"Valde {len(playlist)} låtar. Förbereder..."))

    if playlist:
        first_file_directory = os.path.dirname(playlist[0])
        if start_http_server(first_file_directory):
            run_in_thread(_bg_cast_to_google_home, playlist[0], selected_device)
        else:
            root.after(0, lambda: set_status("Kunde inte starta HTTP-server. Försök igen."))
            playlist = []; current_song_index = 0; root.after(0, update_playlist_display_gui)

def adjust_volume_action(volume_str):
    selected_device = device_var.get()
    if not selected_device: return
    try: volume_float = float(volume_str)
    except ValueError: logging.warning(f"Ogiltigt volymvärde: {volume_str}"); return
    run_in_thread(_bg_adjust_volume, selected_device, volume_float)

def uppdatera_dropdown_action():
    root.after(0, lambda: set_status("Söker efter enheter..."))
    run_in_thread(_bg_hitta_enheter, callback_success=uppdatera_dropdown_gui_callback)

def uppdatera_dropdown_gui_callback(device_names):
    logging.debug(f"GUI_CB: Mottog {len(device_names)} enheter för dropdown.")
    device_dropdown['values'] = device_names
    if device_names:
        current_selection = device_var.get()
        if not current_selection or current_selection not in device_names:
            device_var.set(device_names[0]) # Välj första om inget valt eller om nuvarande försvunnit
        root.after(0, lambda: set_status(f"{len(device_names)} högtalare hittade. '{device_var.get()}' vald."))
        cast = cast_dict.get(device_var.get())
        if cast: run_in_thread(update_volume_label_bg, cast)
    else:
        device_var.set("")
        root.after(0, lambda: set_status("Inga Chromecast-enheter hittades."))

def update_playlist_display_gui():
    # Denna körs alltid i GUI-tråden
    current_items_in_listbox = [playlist_listbox.get(i) for i in range(playlist_listbox.size())]
    new_items_to_display = [os.path.basename(song) for song in playlist]

    if current_items_in_listbox != new_items_to_display:
        playlist_listbox.delete(0, tk.END)
        for song_name in new_items_to_display:
            playlist_listbox.insert(tk.END, song_name)

    for i in range(playlist_listbox.size()):
        playlist_listbox.itemconfig(i, {'fg': 'black'}) # Återställ färg
    if 0 <= current_song_index < playlist_listbox.size():
        playlist_listbox.itemconfig(current_song_index, {'fg': 'blue'})
        playlist_listbox.selection_clear(0, tk.END)
        playlist_listbox.selection_set(current_song_index)
        playlist_listbox.see(current_song_index) # Scrolla till aktuell


def play_selected_song_action(event):
    selection = playlist_listbox.curselection()
    if not selection: return
    index = selection[0]
    selected_device = device_var.get()
    if not selected_device:
        root.after(0, lambda: set_status("Välj en Chromecast-högtalare först."))
        return
    if 0 <= index < len(playlist):
        global current_song_index
        current_song_index = index
        selected_file_directory = os.path.dirname(playlist[current_song_index])
        if start_http_server(selected_file_directory):
            run_in_thread(_bg_cast_to_google_home, playlist[current_song_index], selected_device)
        else:
            root.after(0, lambda: set_status("Kunde inte starta HTTP-server för vald låt."))

def clear_playlist_action():
    global playlist, current_song_index, current_cast, manual_playback_control
    if current_cast:
        run_in_thread(_bg_stop_playback, current_cast.name) # Stoppa i tråd
    playlist = []
    current_song_index = 0
    current_cast = None # Nollställ current_cast
    manual_playback_control = False # Återställ
    root.after(0, update_playlist_display_gui)
    root.after(0, lambda: set_status("Spellista rensad."))
    root.after(0, lambda: now_playing_label.config(text="Nu spelas: Ingen låt"))


def visa_hjalp_action():
    help_window = tk.Toplevel(root)
    help_window.title("Hjälp - MP3 till Chromecast")
    help_window.geometry("600x500")
    help_window.configure(bg="#f0f2f5")
    scroll = ttk.Scrollbar(help_window); scroll.pack(side=tk.RIGHT, fill=tk.Y)
    text_widget = tk.Text(help_window, wrap='word', yscrollcommand=scroll.set, bg="#ffffff", font=('Segoe UI', 11))
    text_widget.insert(tk.END, help_text); text_widget.config(state=tk.DISABLED)
    text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
    scroll.config(command=text_widget.yview)

def set_status(text):
    # Denna funktion anropas via root.after från trådar, så den körs i GUI-tråden.
    if status_label and status_label.cget("text") != text:
        status_label.config(text=text)
        logging.info(f"Status GUI: {text}") # Logga även statusändringar till fil

def on_closing_action():
    global httpd
    logging.info("Programmet stängs...")
    if httpd:
        logging.debug("Försöker stänga HTTP-server vid avslutning...")
        try:
            httpd.shutdown()
            httpd.server_close()
            logging.info("HTTP-server stängd.")
        except Exception as e:
            logging.error(f"Kunde inte stänga HTTP-servern helt vid avslutning: {e}", exc_info=True)
    time.sleep(0.1)
    root.destroy()


# --- GUI Setup ---
root = tk.Tk()
root.title("MP3 till Chromecast")
root.minsize(700, 650)
root.geometry("700x650") # Startstorlek
root.configure(bg="#f0f2f5")

style = ttk.Style()
style.theme_use('clam') # Eller 'alt', 'default', 'classic'
style.configure('TFrame', background="#f0f2f5")
style.configure('TLabel', background="#f0f2f5", font=('Segoe UI', 9))
style.configure('TButton', font=('Segoe UI', 10, 'bold'), padding=(10,5), background="#4CAF50", foreground="white")
style.map('TButton', background=[('active', '#45a049')]) # Mörkare grön vid hover/klick
style.configure('Danger.TButton', background="#f44336", foreground="white") # Röd knapp för "Rensa"
style.map('Danger.TButton', background=[('active', '#da190b')])
style.configure('Horizontal.TScale', background="#f0f2f5")
style.configure('TCombobox', font=('Segoe UI', 10), padding=5)
style.map('TCombobox', fieldbackground=[('readonly', 'white')])


# Toppsektion: Enhetsval och laddningsknapp
top_frame = ttk.Frame(root, padding="10 10 10 0")
top_frame.pack(fill='x')

ttk.Label(top_frame, text="Välj Chromecast:", font=('Segoe UI', 12, 'bold')).pack(side=tk.LEFT, padx=(0,10))
device_var = tk.StringVar()
device_dropdown = ttk.Combobox(top_frame, textvariable=device_var, state='readonly', width=25, style='TCombobox')
device_dropdown.pack(side=tk.LEFT, padx=(0,10), fill='x', expand=True)
ttk.Button(top_frame, text="Uppdatera enheter", command=uppdatera_dropdown_action).pack(side=tk.LEFT)

# Nu spelas-sektion
now_playing_frame = ttk.Frame(root, padding="10 5")
now_playing_frame.pack(fill='x')
ttk.Label(now_playing_frame, text="Nu spelas:", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
now_playing_label = ttk.Label(now_playing_frame, text="Ingen låt", font=('Segoe UI', 10, 'italic'), wraplength=650)
now_playing_label.pack(anchor='w', fill='x')

# Kontrollsektion: Lägg till filer, Rensa spellista
file_control_frame = ttk.Frame(root, padding="10 5")
file_control_frame.pack(fill='x')
ttk.Button(file_control_frame, text="Lägg till MP3-filer", command=välj_filer_action).pack(side=tk.LEFT, padx=(0,5))
ttk.Button(file_control_frame, text="Rensa spellista", command=clear_playlist_action, style='Danger.TButton').pack(side=tk.LEFT)


# Volymkontroll
volume_control_frame = ttk.Frame(root, padding="10 5")
volume_control_frame.pack(fill='x')
ttk.Label(volume_control_frame, text="Volym:", font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=(0,5))
volume_slider = ttk.Scale(volume_control_frame, from_=0, to=100, orient=tk.HORIZONTAL,
                          length=200, command=adjust_volume_action) # command är nu adjust_volume_action
volume_slider.set(50) # Default värde
volume_slider.pack(side=tk.LEFT, padx=(0,5))
volume_label = ttk.Label(volume_control_frame, text="Volym: 50%", font=('Segoe UI', 10)) # Startvärde
volume_label.pack(side=tk.LEFT)

# Spelkontroller: Paus/Spela, Stopp
play_control_frame = ttk.Frame(root, padding="10 5")
play_control_frame.pack(fill='x')
ttk.Button(play_control_frame, text="Paus/Spela",
           command=lambda: run_in_thread(_bg_pause_playback, device_var.get()) if device_var.get() else set_status("Välj en enhet först.")
          ).pack(side=tk.LEFT, padx=(0,5))
ttk.Button(play_control_frame, text="Stopp", style='Danger.TButton',
           command=lambda: run_in_thread(_bg_stop_playback, device_var.get()) if device_var.get() else set_status("Välj en enhet först.")
          ).pack(side=tk.LEFT)


# Spellista
playlist_frame = ttk.Frame(root, padding="10 5")
playlist_frame.pack(fill=tk.BOTH, expand=True)

ttk.Label(playlist_frame, text="Spellista:", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
scrollbar_y = ttk.Scrollbar(playlist_frame, orient=tk.VERTICAL)
scrollbar_x = ttk.Scrollbar(playlist_frame, orient=tk.HORIZONTAL)

playlist_listbox = tk.Listbox(playlist_frame,
                              width=60, height=10, # Justera höjd efter behov
                              bg="white", font=('Segoe UI', 10),
                              yscrollcommand=scrollbar_y.set,
                              xscrollcommand=scrollbar_x.set,
                              selectmode=tk.SINGLE)

scrollbar_y.config(command=playlist_listbox.yview)
scrollbar_x.config(command=playlist_listbox.xview)

scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
playlist_listbox.pack(fill=tk.BOTH, expand=True, pady=(0,5)) # Lite padding under innan x-scrollbaren

playlist_listbox.bind('<Double-1>', play_selected_song_action)


# Bottensektion: Hjälpknapp och status
bottom_frame = ttk.Frame(root, padding="10 10 10 10")
bottom_frame.pack(fill='x')
ttk.Button(bottom_frame, text="Hjälp", command=visa_hjalp_action).pack(side=tk.LEFT)
status_label = ttk.Label(bottom_frame, text="Välkommen! Söker enheter...", foreground="#006d5b", font=('Segoe UI', 10, 'italic'), wraplength=500)
status_label.pack(side=tk.LEFT, padx=20, fill='x', expand=True)


# --- Programstart och avslutning ---
# Sök efter enheter direkt när programmet startar
root.after(100, uppdatera_dropdown_action) # Liten fördröjning för att GUI ska ritas upp först

# Hantera stängning av fönstret
root.protocol("WM_DELETE_WINDOW", on_closing_action)

# Starta Tkinter event loop
root.mainloop()
