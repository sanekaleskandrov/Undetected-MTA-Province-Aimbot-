"""
Color Assist Tool — v7
=======================
pip install numpy opencv-python pygame pillow keyboard

python color_assist.py
"""

import tkinter as tk
from tkinter import ttk, colorchooser
import threading
import time
import math
import ctypes
import ctypes.wintypes
import os
import io

import numpy as np
import cv2
import pygame
import keyboard
from PIL import ImageGrab, Image

# ── WinAPI для мыши ───────────────────────────────────────────────────────────

def mouse_move(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))

def mouse_pos():
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

# ── Захват экрана через PIL (координаты совпадают с SetCursorPos) ─────────────

def grab_screen():
    """
    PIL.ImageGrab.grab() — захватывает в ЛОГИЧЕСКИХ координатах Windows.
    Те же координаты что у SetCursorPos. Никакого DPI пересчёта не нужно.
    Возвращает BGR numpy-массив.
    """
    img = ImageGrab.grab(all_screens=False)
    rgb = np.array(img, dtype=np.uint8)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


# ─────────────────────────────────────────────────────────────────────────────
# Трекер
# ─────────────────────────────────────────────────────────────────────────────

class ColorTracker:
    def __init__(self):
        self._lock         = threading.Lock()
        self.running       = False
        self.thread        = None

        self._target_color = (255, 0, 0)   # RGB
        self._tolerance    = 30
        self._smoothing    = 0.10
        self._fps_limit    = 30            # PIL медленнее mss, 30 FPS достаточно
        self.enabled       = False

        self.fps           = 0.0
        self.found         = False
        self.target_pos    = None          # (x, y) — логические координаты

    @property
    def target_color(self):
        with self._lock: return self._target_color
    @target_color.setter
    def target_color(self, v):
        with self._lock: self._target_color = tuple(v)

    @property
    def tolerance(self):
        with self._lock: return self._tolerance
    @tolerance.setter
    def tolerance(self, v):
        with self._lock: self._tolerance = int(v)

    @property
    def smoothing(self):
        with self._lock: return self._smoothing
    @smoothing.setter
    def smoothing(self, v):
        with self._lock: self._smoothing = float(v)

    @property
    def fps_limit(self):
        with self._lock: return self._fps_limit
    @fps_limit.setter
    def fps_limit(self, v):
        with self._lock: self._fps_limit = max(1, int(v))

    @staticmethod
    def _find(bgr, rgb, tol):
        r, g, b = rgb
        lo = np.array([max(0,   b-tol), max(0,   g-tol), max(0,   r-tol)], dtype=np.uint8)
        hi = np.array([min(255, b+tol), min(255, g+tol), min(255, r+tol)], dtype=np.uint8)

        mask = cv2.inRange(bgr, lo, hi)
        k    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)

        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return None

        best = max(cnts, key=cv2.contourArea)
        if cv2.contourArea(best) < 40:
            return None

        M = cv2.moments(best)
        if M["m00"] == 0:
            return None

        return int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])

    def _loop(self):
        prev = time.perf_counter()

        while self.running:
            t0 = time.perf_counter()

            if self.enabled:
                # Захват в логических координатах
                bgr = grab_screen()

                result = self._find(bgr, self.target_color, self.tolerance)

                if result:
                    tx, ty = result          # уже в логических координатах!
                    self.found      = True
                    self.target_pos = (tx, ty)

                    cx, cy = mouse_pos()
                    s      = self.smoothing
                    nx     = cx + (tx - cx) * (1.0 - s)
                    ny     = cy + (ty - cy) * (1.0 - s)
                    mouse_move(nx, ny)
                else:
                    self.found      = False
                    self.target_pos = None
            else:
                self.found      = False
                self.target_pos = None

            now      = time.perf_counter()
            self.fps = 1.0 / max(now - prev, 1e-9)
            prev     = now

            sleep = 1.0 / self.fps_limit - (now - t0)
            if sleep > 0:
                time.sleep(sleep)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.thread  = threading.Thread(target=self._loop, daemon=True, name="Tracker")
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)


# ─────────────────────────────────────────────────────────────────────────────
# Пипетка
# ─────────────────────────────────────────────────────────────────────────────

class Eyedropper:
    def __init__(self, callback):
        self.callback = callback

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        scr     = ImageGrab.grab(all_screens=False)
        scr_arr = np.array(scr)   # RGB

        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.01)
        root.configure(cursor="crosshair", bg="black")
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"{sw}x{sh}+0+0")

        tk.Label(root,
                 text="  🔍  Кликните на нужный цвет      ESC — отмена  ",
                 font=("Consolas", 11, "bold"),
                 bg="#1a1a2e", fg="#00FF88", pady=8
                 ).place(relx=0.5, y=18, anchor="n")

        mag = tk.Toplevel(root)
        mag.overrideredirect(True)
        mag.attributes("-topmost", True)
        mag.geometry("200x136+10+10")
        mag.configure(bg="#111")
        cnv = tk.Canvas(mag, width=200, height=112, bg="#111", highlightthickness=0)
        cnv.pack()
        lbl = tk.Label(mag, text="", bg="#111", fg="#fff", font=("Consolas", 9))
        lbl.pack()

        def update(x, y):
            x0 = max(0, x-8); y0 = max(0, y-8)
            x1 = min(scr_arr.shape[1], x+9)
            y1 = min(scr_arr.shape[0], y+9)
            patch = scr_arr[y0:y1, x0:x1]
            if patch.size == 0: return
            zoomed = cv2.resize(patch, (200, 112), interpolation=cv2.INTER_NEAREST)
            buf = io.BytesIO()
            Image.fromarray(zoomed).save(buf, "PPM")
            buf.seek(0)
            try:
                ph = tk.PhotoImage(data=buf.read())
                cnv.ph = ph
                cnv.create_image(0, 0, anchor="nw", image=ph)
            except Exception:
                pass
            cnv.create_line(100, 0, 100, 112, fill="#00FF88", width=1)
            cnv.create_line(0, 56, 200, 56, fill="#00FF88", width=1)
            px = min(x, scr_arr.shape[1]-1)
            py = min(y, scr_arr.shape[0]-1)
            r, g, b = int(scr_arr[py,px,0]), int(scr_arr[py,px,1]), int(scr_arr[py,px,2])
            hex_c = f"#{r:02X}{g:02X}{b:02X}"
            lbl.config(text=f"rgb({r},{g},{b})  {hex_c}",
                       bg=hex_c, fg="white" if r*0.299+g*0.587+b*0.114 < 140 else "black")
            mx2 = x+24 if x < sw-230 else x-224
            my2 = y+24 if y < sh-160 else y-160
            mag.geometry(f"200x136+{mx2}+{my2}")

        def on_click(e):
            px = min(e.x_root, scr_arr.shape[1]-1)
            py = min(e.y_root, scr_arr.shape[0]-1)
            r, g, b = int(scr_arr[py,px,0]), int(scr_arr[py,px,1]), int(scr_arr[py,px,2])
            mag.destroy(); root.destroy()
            self.callback(r, g, b)

        root.bind("<Motion>",   lambda e: update(e.x_root, e.y_root))
        root.bind("<Button-1>", on_click)
        root.bind("<Escape>",   lambda e: (mag.destroy(), root.destroy()))
        root.focus_force()
        root.mainloop()


# ─────────────────────────────────────────────────────────────────────────────
# Pygame-оверлей FOV
# ─────────────────────────────────────────────────────────────────────────────

class PygameOverlay:
    CK = (1, 1, 1)

    def __init__(self, state):
        self.state  = state
        self.thread = threading.Thread(target=self._run, daemon=True, name="Overlay")

    def start(self): self.thread.start()

    def _run(self):
        os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"
        pygame.init()
        info   = pygame.display.Info()
        sw, sh = info.current_w, info.current_h
        screen = pygame.display.set_mode((sw, sh), pygame.NOFRAME)
        pygame.display.set_caption("__color_assist_v6__")
        self._winapi(sw, sh)
        clock = pygame.time.Clock()

        while self.state.get("running", True):
            for _ in pygame.event.get(): pass
            screen.fill(self.CK)

            if self.state.get("show", False):
                mx = self.state.get("mx", sw//2)
                my = self.state.get("my", sh//2)
                r  = self.state.get("radius", 200)
                tg = self.state.get("target", None)

                self._circle(screen, (0,255,136), mx, my, r, 2)
                pygame.draw.line(screen, (0,255,136), (mx-8,my),(mx+8,my), 1)
                pygame.draw.line(screen, (0,255,136), (mx,my-8),(mx,my+8), 1)
                if tg:
                    tx, ty = tg
                    self._dline(screen, (255,80,80), mx, my, tx, ty)
                    pygame.draw.circle(screen, (255,80,80), (tx,ty), 11, 2)
                    pygame.draw.circle(screen, (255,230,0), (tx,ty), 3)

            pygame.display.flip()
            clock.tick(60)
        pygame.quit()

    def _winapi(self, sw, sh):
        time.sleep(0.4)
        try:
            found = []
            def cb(h, _):
                buf = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetWindowTextW(h, buf, 256)
                if buf.value == "__color_assist_v6__": found.append(h)
                return True
            FN = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            ctypes.windll.user32.EnumWindows(FN(cb), 0)
            if not found: return
            hwnd = found[0]
            cur  = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20,
                cur | 0x00080000 | 0x00000020 | 0x00000080)
            r,g,b = self.CK
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, r|(g<<8)|(b<<16), 0, 1)
            ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, sw, sh, 0x0003)
        except Exception as e:
            print(f"[Overlay] {e}")

    @staticmethod
    def _circle(surf, col, cx, cy, r, w):
        segs = max(16, int(2*math.pi*r/10))
        for i in range(segs):
            a0 = 2*math.pi*i/segs
            a1 = 2*math.pi*(i+0.55)/segs
            n  = max(2, int((a1-a0)*r))
            pts = [(cx+r*math.cos(a0+(a1-a0)*t/n),
                    cy+r*math.sin(a0+(a1-a0)*t/n)) for t in range(n+1)]
            if len(pts) >= 2:
                pygame.draw.lines(surf, col, False, pts, w)

    @staticmethod
    def _dline(surf, col, x1,y1,x2,y2, w=1,d=8,g=5):
        dx,dy = x2-x1,y2-y1; L = math.hypot(dx,dy)
        if L == 0: return
        ux,uy = dx/L,dy/L; pos,on = 0.0,True
        while pos < L:
            s = d if on else g; e = min(pos+s, L)
            if on:
                pygame.draw.line(surf, col,
                    (int(x1+ux*pos), int(y1+uy*pos)),
                    (int(x1+ux*e),   int(y1+uy*e)), w)
            pos += s; on = not on


# ─────────────────────────────────────────────────────────────────────────────
# Глобальный хоткей (работает даже когда окно не в фокусе)
# ─────────────────────────────────────────────────────────────────────────────

class HotkeyManager:
    """
    Регистрирует глобальный хоткей через библиотеку keyboard.
    Хоткей переключает трекинг (toggle) — работает в любом окне.
    """

    def __init__(self, callback):
        self.callback    = callback   # fn() — вызывается при нажатии
        self._hotkey     = "F8"       # дефолтный бинд
        self._registered = False
        self._waiting    = False      # режим ожидания нового бинда

    @property
    def hotkey(self):
        return self._hotkey

    def register(self, key: str):
        """Зарегистрировать новый хоткей. Старый снимается."""
        try:
            if self._registered:
                keyboard.remove_hotkey(self._hotkey)
                self._registered = False
        except Exception:
            pass

        try:
            keyboard.add_hotkey(key, self.callback, suppress=False)
            self._hotkey     = key
            self._registered = True
            return True
        except Exception as e:
            print(f"[Hotkey] Ошибка регистрации '{key}': {e}")
            return False

    def unregister(self):
        try:
            if self._registered:
                keyboard.remove_hotkey(self._hotkey)
                self._registered = False
        except Exception:
            pass

    def start_capture(self, on_captured):
        """
        Ждёт нажатия любой клавиши и возвращает её имя через on_captured(key).
        Работает в отдельном потоке чтобы не блокировать GUI.
        """
        def _wait():
            self._waiting = True
            try:
                # Временно снимаем текущий хоткей чтобы поймать его тоже
                self.unregister()
                event = keyboard.read_event(suppress=True)
                # Пропускаем keyup
                while event.event_type != "down":
                    event = keyboard.read_event(suppress=True)
                key = event.name
                self._waiting = False
                on_captured(key)
            except Exception as e:
                self._waiting = False
                print(f"[Hotkey capture] {e}")

        threading.Thread(target=_wait, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────────────────────────────────────

class App:
    BG  = "#1a1a2e"
    FG  = "#dde0ff"
    ACC = "#00FF88"
    BTN = "#16213e"
    ENT = "#0f3460"

    def __init__(self):
        self.ov = {"running":True,"show":False,
                   "mx":0,"my":0,"radius":200,"target":None}

        self.overlay = PygameOverlay(self.ov)
        self.overlay.start()

        self.tracker = ColorTracker()
        self.tracker.start()

        # Хоткей
        self.hotkey_mgr = HotkeyManager(self._toggle)
        self.hotkey_mgr.register("F8")

        self.win = tk.Tk()
        self.win.title("A1m b0t")
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self.win.configure(bg=self.BG)
        self.win.attributes("-topmost", True)

        self._build_ui()
        self._tick()
        self.win.mainloop()

    def _build_ui(self):
        w = self.win
        BG,FG,ACC,BTN,ENT = self.BG,self.FG,self.ACC,self.BTN,self.ENT

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TScale", background=BG, troughcolor=ENT,
                        sliderlength=22, sliderrelief="flat")
        style.map("TScale", background=[("active", BG)])
        p = dict(padx=16, pady=5)

        tk.Label(w, text="Аимбот по цвету",
                 font=("Consolas",14,"bold"), bg=BG, fg=ACC
                 ).grid(row=0,column=0,columnspan=3,pady=(14,2))
        tk.Label(w, text="Лучше ставьте в играх оконный режим",
                 font=("Consolas",9), bg=BG, fg="#444"
                 ).grid(row=1,column=0,columnspan=3,pady=(0,10))

        # Цвет
        tk.Label(w,text="Цвет цели:",bg=BG,fg=FG,
                 font=("Consolas",10)).grid(row=2,column=0,sticky="w",**p)
        cf = tk.Frame(w,bg=BG)
        cf.grid(row=2,column=1,columnspan=2,sticky="w",**p)
        self.swatch = tk.Label(cf,text="       ",bg="#FF0000",
                                width=5,cursor="hand2",relief="flat")
        self.swatch.pack(side="left",padx=(0,8))
        self.swatch.bind("<Button-1>", lambda _: self._dialog_color())
        self.color_lbl = tk.Label(cf,text="rgb(255, 0, 0)",
                                   bg=BG,fg=FG,font=("Consolas",9))
        self.color_lbl.pack(side="left")
        tk.Button(cf,text="Пипетка",
                  font=("Consolas",9),bg=ENT,fg=ACC,
                  relief="flat",bd=0,cursor="hand2",padx=10,pady=3,
                  command=self._start_eyedropper
                  ).pack(side="left",padx=(12,0))

        # Слайдеры
        sliders = [
            ("Допуск цвета:", "_tol", 1,  120, 30,   False, "d"),
            ("FOV радиус:",   "_rad", 60, 600, 200,  False, "d"),
            ("Плавность:",    "_smo", 0.0,0.95,0.10, True,  ".2f"),
            ("Лимит FPS:",    "_fpl", 5,  60,  30,   False, "d"),
        ]
        for row,(lbl,attr,lo,hi,default,is_f,fmt) in enumerate(sliders,start=3):
            tk.Label(w,text=lbl,bg=BG,fg=FG,
                     font=("Consolas",10)).grid(row=row,column=0,sticky="w",**p)
            var = tk.DoubleVar(value=default) if is_f else tk.IntVar(value=default)
            setattr(self, attr, var)
            val_lbl = tk.Label(w,text=f"{default:{fmt}}",
                                bg=BG,fg=ACC,font=("Consolas",9),width=5)
            val_lbl.grid(row=row,column=2,sticky="e",padx=16)
            def _cb(v=var,lbl=val_lbl,f=fmt):
                def _(*_): lbl.config(text=f"{v.get():{f}}"); self._sync()
                return _
            ttk.Scale(w,from_=lo,to=hi,variable=var,
                      orient="horizontal",length=180,command=_cb()
                      ).grid(row=row,column=1,sticky="w",**p)

        tk.Frame(w,bg="#252545",height=1).grid(
            row=7,column=0,columnspan=3,sticky="ew",pady=8,padx=16)

        # ── Хоткей ──
        hf = tk.Frame(w, bg=BG)
        hf.grid(row=8, column=0, columnspan=3, sticky="ew", padx=16, pady=(0,6))

        tk.Label(hf, text="Бинд:", bg=BG, fg=FG,
                 font=("Consolas", 10)).pack(side="left")

        self.bind_lbl = tk.Label(hf, text="  F8  ",
                                  bg=ENT, fg=ACC,
                                  font=("Consolas", 10, "bold"),
                                  padx=8, pady=3, relief="flat")
        self.bind_lbl.pack(side="left", padx=(8, 0))

        self.bind_btn = tk.Button(hf, text="Изменить",
                                   font=("Consolas", 9), bg=BTN, fg=FG,
                                   relief="flat", bd=0, cursor="hand2",
                                   padx=10, pady=3,
                                   command=self._start_bind_capture)
        self.bind_btn.pack(side="left", padx=(8, 0))

        tk.Frame(w,bg="#252545",height=1).grid(
            row=9,column=0,columnspan=3,sticky="ew",pady=(0,6),padx=16)

        self.tog = tk.Button(
            w,text="ВКЛЮЧИТЬ ТРЕКИНГ",
            font=("Consolas",11,"bold"),
            bg=BTN,fg=FG,relief="flat",cursor="hand2",
            pady=10,bd=0,highlightthickness=0,
            command=self._toggle
        )
        self.tog.grid(row=10,column=0,columnspan=3,sticky="ew",padx=16,pady=(0,6))

        self.fov_var = tk.BooleanVar(value=True)
        tk.Checkbutton(w,text="Показывать FOV-круг",
                       variable=self.fov_var,bg=BG,fg=FG,
                       selectcolor=BTN,activebackground=BG,activeforeground=ACC,
                       font=("Consolas",9),command=self._sync_overlay
                       ).grid(row=11,column=0,columnspan=3,sticky="w",padx=16,pady=2)

        sf = tk.Frame(w,bg=BG)
        sf.grid(row=12,column=0,columnspan=3,sticky="ew",padx=16,pady=(6,2))
        self.stat = tk.Label(sf,text="● Выключен",
                              font=("Consolas",9),bg=BG,fg="#555")
        self.stat.pack(side="left")
        self.fps_lbl = tk.Label(sf,text="",font=("Consolas",9),bg=BG,fg="#555")
        self.fps_lbl.pack(side="right")

        tk.Label(w,text="⚠  Аварийная остановка: мышь → верхний левый угол",
                 font=("Consolas",8),bg=BG,fg="#2e2e4e"
                 ).grid(row=13,column=0,columnspan=3,pady=(4,14))

    def _set_color(self, r, g, b):
        self.tracker.target_color = (r, g, b)
        self.swatch.config(bg=f"#{r:02X}{g:02X}{b:02X}")
        self.color_lbl.config(text=f"rgb({r}, {g}, {b})")

    def _dialog_color(self):
        r,g,b = self.tracker.target_color
        res = colorchooser.askcolor(color=f"#{r:02X}{g:02X}{b:02X}",
                                    title="Выберите цвет",parent=self.win)
        if res and res[0]:
            self._set_color(*[int(c) for c in res[0]])

    def _start_eyedropper(self):
        self.win.withdraw()
        def done(r,g,b):
            self._set_color(r,g,b)
            self.win.deiconify()
            self.win.attributes("-topmost",True)
        Eyedropper(done).start()

    def _sync(self):
        self.tracker.tolerance = int(self._tol.get())
        self.tracker.smoothing = float(self._smo.get())
        self.tracker.fps_limit = int(self._fpl.get())
        self.ov["radius"]      = int(self._rad.get())

    def _sync_overlay(self):
        self.ov["show"] = self.tracker.enabled and self.fov_var.get()

    def _toggle(self):
        self.tracker.enabled = not self.tracker.enabled
        on = self.tracker.enabled
        self.tog.config(
            text="ОСТАНОВИТЬ ТРЕКИНГ" if on else "ВКЛЮЧИТЬ ТРЕКИНГ",
            fg=self.ACC if on else self.FG)
        self.stat.config(
            text="● Активен" if on else "● Выключен",
            fg=self.ACC if on else "#555")
        self._sync_overlay()

    def _tick(self):
        try:
            if self.tracker.enabled:
                if self.tracker.found:
                    self.stat.config(text="Цель найдена!", fg=self.ACC)
                    self.fps_lbl.config(text=f"FPS: {self.tracker.fps:.0f}", fg=self.ACC)
                else:
                    self.stat.config(text="● Активен — не найдено", fg="#FFA500")
                    self.fps_lbl.config(text=f"FPS: {self.tracker.fps:.0f}", fg="#FFA500")
            mx, my = mouse_pos()
            self.ov["mx"]     = mx
            self.ov["my"]     = my
            self.ov["target"] = self.tracker.target_pos
        except Exception:
            pass
        finally:
            self.win.after(33, self._tick)

    def _start_bind_capture(self):
        """Переходим в режим ожидания нового бинда."""
        self.bind_btn.config(state="disabled")
        self.bind_lbl.config(text=" Нажмите клавишу... ", fg="#FFA500")

        def on_captured(key):
            ok = self.hotkey_mgr.register(key)
            # Обновляем UI из главного потока
            def update():
                if ok:
                    self.bind_lbl.config(
                        text=f"  {key.upper()}  ", fg=self.ACC)
                else:
                    self.bind_lbl.config(
                        text=f"  ОШИБКА  ", fg="#FF4444")
                self.bind_btn.config(state="normal")
            self.win.after(0, update)

        self.hotkey_mgr.start_capture(on_captured)

    def _on_close(self):
        self.hotkey_mgr.unregister()
        self.ov["running"] = False
        self.tracker.stop()
        time.sleep(0.2)
        self.win.destroy()


if __name__ == "__main__":
    App()
