import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path
import io
import contextlib
import threading
import subprocess
import sys
import time
import queue
from datetime import datetime

from flight_model_paramaterized import run_flight


# ============================================================
# BALLOON FLIGHT PREDICTION GUI
# PARAMETERIZED VERSION
# ============================================================

OUTPUT_FILE = r"C:\Users\Praveen Vasudevan\Desktop\SFT\balloon_burst_calculator\results"


class LiveOutputStream:
    """
    Thread-safe stdout stream.

    The simulation runs in a worker thread. Every print() from the
    flight model is placed in a queue so the Tkinter GUI can display
    it live without touching Tkinter from the worker thread.
    """

    def __init__(self):
        self.queue = queue.Queue()
        self.all_output = []

    def write(self, text):
        if text:
            self.all_output.append(text)
            self.queue.put(text)

    def flush(self):
        pass

    def get_all_output(self):
        return "".join(self.all_output)



import re


# ============================================================
# LIGHT AEROSPACE MISSION-CONTROL THEME
# ============================================================

BG = "#F3F6FA"
CARD = "#FFFFFF"
TEXT = "#182230"
MUTED = "#667085"
ACCENT = "#2F6FED"
ACCENT_DARK = "#2457BA"
ACCENT_LIGHT = "#EAF1FF"
SUCCESS = "#15803D"
SUCCESS_LIGHT = "#EAF7EE"
WARNING = "#B45309"
WARNING_LIGHT = "#FFF4E5"
DANGER = "#B42318"
DANGER_LIGHT = "#FEECEC"
BORDER = "#D9E1EA"
LOG_BG = "#F8FAFC"


class LiveOutputStream:
    """Thread-safe stdout stream used to stream backend output to Tk."""

    def __init__(self):
        self.queue = queue.Queue()

    def write(self, text):
        if text:
            self.queue.put(text)

    def flush(self):
        pass



class BalloonFlightGUI:

    def __init__(self):

        self.root = tk.Tk()
        self.root.title("Balloon GNC — Mission Control")
        self.root.geometry("1280x760")
        self.root.minsize(1050, 700)
        self.root.configure(bg=BG)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "TEntry",
            padding=7,
            fieldbackground="white"
        )

        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=BORDER,
            background=ACCENT,
            lightcolor=ACCENT,
            darkcolor=ACCENT
        )

        self.entries = {}

        self._worker_done = False
        self._worker_result = None
        self._worker_error = None
        self._worker_stream = None
        self._worker_start_time = None
        self._displayed_output = ""

        self._build_header()
        self._build_main()
        self._build_footer()

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.root.destroy
        )

    # ========================================================
    # HEADER
    # ========================================================

    def _build_header(self):

        header = tk.Frame(
            self.root,
            bg=BG
        )
        header.pack(
            fill="x",
            padx=28,
            pady=(20, 12)
        )

        title_box = tk.Frame(
            header,
            bg=BG
        )
        title_box.pack(
            side="left"
        )

        tk.Label(
            title_box,
            text="BALLOON GNC",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 25, "bold")
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text="Super-Pressure Balloon Flight Simulation • Mission Control",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10)
        ).pack(
            anchor="w",
            pady=(2, 0)
        )

        self.system_badge = tk.Label(
            header,
            text="●  SYSTEM READY",
            bg=SUCCESS_LIGHT,
            fg=SUCCESS,
            font=("Segoe UI", 10, "bold"),
            padx=15,
            pady=7
        )
        self.system_badge.pack(
            side="right",
            pady=6
        )

    # ========================================================
    # MAIN
    # ========================================================

    def _build_main(self):

        main = tk.Frame(
            self.root,
            bg=BG
        )
        main.pack(
            fill="both",
            expand=True,
            padx=28,
            pady=(0, 10)
        )

        main.columnconfigure(0, weight=0, minsize=325)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        self._build_parameters(main)
        self._build_live_panel(main)

    # ========================================================
    # PARAMETERS
    # ========================================================

    def _build_parameters(self, parent):

        card = tk.Frame(
            parent,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1
        )
        card.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 12)
        )

        tk.Label(
            card,
            text="MISSION PARAMETERS",
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 12, "bold")
        ).pack(
            anchor="w",
            padx=18,
            pady=(14, 0)
        )

        tk.Label(
            card,
            text="Flight and vehicle configuration",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 8)
        ).pack(
            anchor="w",
            padx=18,
            pady=(1, 7)
        )

        # Two-column compact parameter layout.
        form = tk.Frame(
            card,
            bg=CARD
        )
        form.pack(
            fill="x",
            padx=14
        )

        fields = [
            ("Launch Latitude (°)", "13.0827"),
            ("Launch Longitude (°)", "80.2707"),
            ("Launch Altitude (m)", "87"),
            ("Launch Date & Time", "2026-10-02 00:00"),
            ("Ascent Rate (m/s)", "6.69"),
            ("Descent Rate (m/s)", "5.0"),
            ("Ascent Time Step (s)", "10"),
            ("Descent Time Step (s)", "1"),
            ("Target Burst Altitude (km)", "32"),
            ("Maximum Altitude / Safety Ceiling (km)", "35"),
            ("Ground Altitude (m)", "87"),
            ("Payload Mass (kg)", "5"),
            ("Envelope Mass (kg)", "3"),
            ("Helium Mass (kg)", "2"),
            ("Initial Volume (m³)", "12.05"),
            ("Burst Diameter (m) - monitoring only", "13.02"),
            ("Parachute Diameter (m)", "2.4"),
            ("Parachute Cd", "1"),
        ]

        self.entries = {}

        split = (len(fields) + 1) // 2

        for i, (label, default) in enumerate(fields):

            if i < split:
                row = i
                col = 0
            else:
                row = i - split
                col = 1

            block = tk.Frame(
                form,
                bg=CARD
            )
            block.grid(
                row=row,
                column=col,
                sticky="ew",
                padx=4,
                pady=2
            )

            tk.Label(
                block,
                text=label,
                bg=CARD,
                fg=MUTED,
                font=("Segoe UI", 7)
            ).pack(
                anchor="w"
            )

            entry = ttk.Entry(
                block,
                width=16
            )
            entry.insert(
                0,
                default
            )
            entry.pack(
                fill="x",
                pady=(1, 0)
            )

            self.entries[label] = entry

        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)

        # Buttons are deliberately outside the parameter grid,
        # so they are always visible on the single-page dashboard.
        buttons = tk.Frame(
            card,
            bg=CARD
        )
        buttons.pack(
            fill="x",
            padx=18,
            pady=(10, 14)
        )

        self.run_button = tk.Button(
            buttons,
            text="▶  RUN SIMULATION",
            command=self.run_simulation,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_DARK,
            activeforeground="white",
            relief="flat",
            bd=0,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            pady=9
        )
        self.run_button.pack(
            fill="x"
        )

        self.plot_button = tk.Button(
            buttons,
            text="↗  OPEN TRAJECTORY PLOTS",
            command=self.open_plots,
            bg=ACCENT_LIGHT,
            fg=ACCENT,
            activebackground="#DDE8FF",
            activeforeground=ACCENT_DARK,
            relief="flat",
            bd=0,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            pady=8,
            state="disabled"
        )
        self.plot_button.pack(
            fill="x",
            pady=(6, 0)
        )

    # ========================================================
    # LIVE PANEL
    # ========================================================

    def _build_live_panel(self, parent):

        card = tk.Frame(
            parent,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1
        )
        card.grid(
            row=0,
            column=1,
            sticky="nsew"
        )

        card.rowconfigure(2, weight=1)
        card.columnconfigure(0, weight=1)

        top = tk.Frame(
            card,
            bg=CARD
        )
        top.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=20,
            pady=(17, 10)
        )

        tk.Label(
            top,
            text="LIVE FLIGHT",
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 12, "bold")
        ).pack(side="left")

        self.phase_label = tk.Label(
            top,
            text="● READY",
            bg=ACCENT_LIGHT,
            fg=ACCENT,
            font=("Segoe UI", 9, "bold"),
            padx=13,
            pady=5
        )
        self.phase_label.pack(side="right")

        metrics = tk.Frame(
            card,
            bg=CARD
        )
        metrics.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=16,
            pady=(0, 12)
        )

        for i in range(4):
            metrics.columnconfigure(
                i,
                weight=1
            )

        self.metric_labels = {}

        for i, (name, value) in enumerate([
            ("ALTITUDE", "0.00 km"),
            ("VERTICAL RATE", "0.00 m/s"),
            ("WIND SPEED", "0.00 m/s"),
            ("MISSION TIME", "00:00"),
        ]):

            box = tk.Frame(
                metrics,
                bg=LOG_BG,
                highlightbackground=BORDER,
                highlightthickness=1
            )
            box.grid(
                row=0,
                column=i,
                sticky="ew",
                padx=4
            )

            tk.Label(
                box,
                text=name,
                bg=LOG_BG,
                fg=MUTED,
                font=("Segoe UI", 8, "bold")
            ).pack(
                anchor="w",
                padx=10,
                pady=(8, 0)
            )

            label = tk.Label(
                box,
                text=value,
                bg=LOG_BG,
                fg=TEXT,
                font=("Segoe UI", 15, "bold")
            )
            label.pack(
                anchor="w",
                padx=10,
                pady=(2, 8)
            )

            self.metric_labels[name] = label

        console = tk.Frame(
            card,
            bg=CARD
        )
        console.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=20,
            pady=(0, 15)
        )

        console.rowconfigure(1, weight=1)
        console.columnconfigure(0, weight=1)

        tk.Label(
            console,
            text="LIVE SIMULATION LOG",
            bg=CARD,
            fg=TEXT,
            font=("Segoe UI", 10, "bold")
        ).grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 6)
        )

        self.results = scrolledtext.ScrolledText(
            console,
            height=20,
            wrap=tk.WORD,
            bg=LOG_BG,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground="#CFE0FF",
            selectforeground=TEXT,
            font=("Consolas", 9),
            relief="flat",
            bd=0,
            padx=12,
            pady=10
        )
        self.results.grid(
            row=1,
            column=0,
            sticky="nsew"
        )
        self.results.configure(
            state="disabled"
        )

    # ========================================================
    # FOOTER
    # ========================================================

    def _build_footer(self):

        footer = tk.Frame(
            self.root,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1
        )
        footer.pack(
            fill="x",
            padx=28,
            pady=(0, 20)
        )

        self.status = tk.Label(
            footer,
            text="Ready for launch",
            bg=CARD,
            fg=MUTED,
            font=("Segoe UI", 9),
            anchor="w"
        )
        self.status.pack(
            fill="x",
            padx=15,
            pady=(9, 3)
        )

        self.progress = ttk.Progressbar(
            footer,
            mode="indeterminate"
        )
        self.progress.pack(
            fill="x",
            padx=15,
            pady=(0, 9)
        )

    # ========================================================
    # INPUTS
    # ========================================================

    def get_inputs(self):

        try:

            def val(label):
                return float(
                    self.entries[label].get()
                )

            launch_datetime = datetime.strptime(
                self.entries[
                    "Launch Date & Time"
                ].get().strip(),
                "%Y-%m-%d %H:%M"
            )

            # IMPORTANT:
            # flight_model_parameterized.run_flight()
            # expects these exact dictionary keys:
            # latitude, longitude, launch_altitude,
            # payload_mass, envelope_mass, helium_mass,
            # initial_volume, burst_diameter, balloon_cd,
            # parachute_diameter, parachute_cd,
            # ascent_time_step, descent_time_step,
            # maximum_altitude, ground_altitude,
            # launch_datetime.

            p = {
                "latitude":
                    val("Launch Latitude (°)"),

                "longitude":
                    val("Launch Longitude (°)"),

                "launch_altitude":
                    val("Launch Altitude (m)"),

                "launch_datetime":
                    launch_datetime,

                "payload_mass":
                    val("Payload Mass (kg)"),

                "envelope_mass":
                    val("Envelope Mass (kg)"),

                "helium_mass":
                    val("Helium Mass (kg)"),

                "initial_volume":
                    val("Initial Volume (m³)"),

                "burst_diameter":
                    val("Burst Diameter (m) - monitoring only"),

                "balloon_cd":
                    0.47,

                "parachute_diameter":
                    val("Parachute Diameter (m)"),

                "parachute_cd":
                    val("Parachute Cd"),

                "ascent_time_step":
                    val("Ascent Time Step (s)"),

                "descent_time_step":
                    val("Descent Time Step (s)"),

                "burst_altitude":
                    val("Target Burst Altitude (km)") * 1000,

                "maximum_altitude":
                    val("Maximum Altitude / Safety Ceiling (km)") * 1000,

                "ground_altitude":
                    val("Ground Altitude (m)"),

                # Retained for the next flight-model update.
                # The current flight model calculates ascent rate
                # from balloon physics.
                "ascent_rate":
                    val("Ascent Rate (m/s)"),

                "descent_rate":
                    val("Descent Rate (m/s)")
            }

            if not -90 <= p["latitude"] <= 90:
                raise ValueError(
                    "Latitude must be between -90 and +90 degrees."
                )

            if not -180 <= p["longitude"] <= 180:
                raise ValueError(
                    "Longitude must be between -180 and +180 degrees."
                )

            positive_fields = [
                "payload_mass",
                "envelope_mass",
                "helium_mass",
                "initial_volume",
                "burst_diameter",
                "parachute_diameter",
                "parachute_cd",
                "ascent_time_step",
                "descent_time_step",
                "burst_altitude",
                "maximum_altitude",
            ]

            for key in positive_fields:
                if p[key] <= 0:
                    raise ValueError(
                        f"{key} must be greater than zero."
                    )

            if p["ascent_rate"] <= 0:
                raise ValueError(
                    "Ascent rate must be greater than zero."
                )

            if p["descent_rate"] <= 0:
                raise ValueError(
                    "Descent rate must be greater than zero."
                )

            if p["burst_altitude"] <= p["launch_altitude"]:
                raise ValueError(
                    "Target burst altitude must be above launch altitude."
                )

            if p["burst_altitude"] > p["maximum_altitude"]:
                raise ValueError(
                    "Target burst altitude must not exceed the maximum-altitude safety ceiling."
                )

            if p["ground_altitude"] >= p["maximum_altitude"]:
                raise ValueError(
                    "Ground altitude must be below maximum altitude."
                )

            return p

        except ValueError as error:

            messagebox.showerror(
                "Invalid Input",
                str(error)
            )

            return None

    # ========================================================
    # SIMULATION
    # ========================================================

    def run_simulation(self):

        parameters = self.get_inputs()

        if parameters is None:
            return

        self._worker_done = False
        self._worker_result = None
        self._worker_error = None
        self._worker_stream = LiveOutputStream()
        self._worker_start_time = time.time()
        self._displayed_output = ""

        self.run_button.configure(
            state="disabled"
        )
        self.plot_button.configure(
            state="disabled"
        )

        self.system_badge.configure(
            text="●  SIMULATION RUNNING",
            bg=WARNING_LIGHT,
            fg=WARNING
        )
        self.phase_label.configure(
            text="● INITIALIZING",
            bg=WARNING_LIGHT,
            fg=WARNING
        )

        for label, value in [
            ("ALTITUDE", "0.00 km"),
            ("VERTICAL RATE", "0.00 m/s"),
            ("WIND SPEED", "0.00 m/s"),
            ("MISSION TIME", "00:00"),
        ]:
            self.metric_labels[label].configure(
                text=value
            )

        self.progress.start(10)

        self.results.configure(
            state="normal"
        )
        self.results.delete(
            "1.0",
            tk.END
        )
        self.results.insert(
            tk.END,
            "BALLOON GNC MISSION CONTROL\n"
            "========================================\n\n"
            "Initializing flight simulation...\n"
        )
        self.results.configure(
            state="disabled"
        )

        self.status.configure(
            text="Initializing flight simulation..."
        )

        thread = threading.Thread(
            target=self._simulation_worker,
            args=(parameters,),
            daemon=True
        )
        thread.start()

        self.root.after(
            100,
            self._check_simulation
        )

    def _simulation_worker(self, parameters):

        try:

            with contextlib.redirect_stdout(
                self._worker_stream
            ):
                self._worker_result = run_flight(
                    parameters
                )

        except Exception as error:

            self._worker_error = (
                f"{type(error).__name__}: {error}"
            )

        finally:

            self._worker_done = True

    # ========================================================
    # LIVE OUTPUT
    # ========================================================

    def _update_metrics_from_output(self):

        output = self._displayed_output

        patterns = {
            "ALTITUDE": [
                r"alt\s*=\s*([0-9.+-]+)\s*km",
                r"Altitude\s*:\s*([0-9.+-]+)\s*km",
                r"altitude\s*=\s*([0-9.+-]+)\s*m"
            ],
            "VERTICAL RATE": [
                r"Vup\s*=\s*([0-9.+-]+)\s*m/s",
                r"Ascent rate\s*:\s*([0-9.+-]+)\s*m/s"
            ],
            "WIND SPEED": [
                r"wind\s*=\s*([0-9.+-]+)\s*m/s",
                r"Wind speed\s*:\s*([0-9.+-]+)\s*m/s"
            ],
            "MISSION TIME": [
                r"t\s*=\s*([0-9.+-]+)\s*min",
                r"Time\s*:\s*([0-9.+-]+)\s*(?:s|sec)"
            ]
        }

        for metric, regexes in patterns.items():

            for regex in regexes:

                matches = re.findall(
                    regex,
                    output,
                    flags=re.IGNORECASE
                )

                if not matches:
                    continue

                try:
                    v = float(matches[-1])

                    if metric == "ALTITUDE":
                        # The first two altitude patterns are already km;
                        # the third is metres.
                        if "altitude\\s*=" in regex.lower():
                            display = f"{v / 1000.0:.2f} km"
                        else:
                            display = f"{v:.2f} km"

                    elif metric in (
                        "VERTICAL RATE",
                        "WIND SPEED"
                    ):
                        display = f"{v:.2f} m/s"

                    else:
                        # The live model prints t in minutes.
                        if "min" in regex.lower():
                            total_seconds = v * 60.0
                        else:
                            total_seconds = v

                        minutes = int(total_seconds // 60)
                        seconds = int(total_seconds % 60)
                        display = (
                            f"{minutes:02d}:{seconds:02d}"
                        )

                    self.metric_labels[
                        metric
                    ].configure(
                        text=display
                    )

                except ValueError:
                    pass

                break

    def _set_phase(self, phase):

        styles = {
            "READY": (
                "● READY",
                ACCENT_LIGHT,
                ACCENT
            ),
            "ASCENT": (
                "● ASCENT",
                ACCENT_LIGHT,
                ACCENT
            ),
            "BURST": (
                "● BURST",
                WARNING_LIGHT,
                WARNING
            ),
            "DESCENT": (
                "● DESCENT",
                ACCENT_LIGHT,
                ACCENT
            ),
            "LANDING": (
                "● LANDING",
                SUCCESS_LIGHT,
                SUCCESS
            ),
            "COMPLETE": (
                "● COMPLETE",
                SUCCESS_LIGHT,
                SUCCESS
            ),
            "ERROR": (
                "● ERROR",
                DANGER_LIGHT,
                DANGER
            ),
        }

        text, bg, fg = styles.get(
            phase,
            styles["READY"]
        )

        self.phase_label.configure(
            text=text,
            bg=bg,
            fg=fg
        )

    def _check_simulation(self):

        stream = self._worker_stream

        if stream is not None:

            chunks = []

            while True:

                try:
                    chunks.append(
                        stream.queue.get_nowait()
                    )
                except queue.Empty:
                    break

            if chunks:

                new_text = "".join(chunks)
                self._displayed_output += new_text

                self.results.configure(
                    state="normal"
                )
                self.results.insert(
                    tk.END,
                    new_text
                )
                self.results.see(
                    tk.END
                )
                self.results.configure(
                    state="disabled"
                )

                upper = self._displayed_output.upper()

                if "LANDING" in upper:
                    self._set_phase("LANDING")
                    status = "Landing phase — finalizing trajectory"

                elif "DESCENT" in upper:
                    self._set_phase("DESCENT")
                    status = "Descent phase — following atmospheric wind"

                elif "BURST" in upper:
                    self._set_phase("BURST")
                    status = "Burst detected — transitioning to descent"

                elif "ASCENT" in upper:
                    self._set_phase("ASCENT")
                    status = "Ascent phase — climbing at commanded rate"

                else:
                    status = "Processing flight simulation"

                elapsed = (
                    time.time()
                    - self._worker_start_time
                )

                self.status.configure(
                    text=f"{status}  •  {elapsed:.0f} s elapsed"
                )

                self._update_metrics_from_output()

        if not self._worker_done:

            self.root.after(
                100,
                self._check_simulation
            )
            return

        self.progress.stop()
        self.run_button.configure(
            state="normal"
        )

        # Drain final messages.
        if stream is not None:

            final = []

            while True:

                try:
                    final.append(
                        stream.queue.get_nowait()
                    )
                except queue.Empty:
                    break

            if final:

                final_text = "".join(final)
                self._displayed_output += final_text

                self.results.configure(
                    state="normal"
                )
                self.results.insert(
                    tk.END,
                    final_text
                )
                self.results.see(
                    tk.END
                )
                self.results.configure(
                    state="disabled"
                )

        self._update_metrics_from_output()

        if self._worker_error:

            self.system_badge.configure(
                text="●  SIMULATION ERROR",
                bg=DANGER_LIGHT,
                fg=DANGER
            )

            self._set_phase("ERROR")

            self.status.configure(
                text="Simulation failed"
            )

            self.results.configure(
                state="normal"
            )
            self.results.insert(
                tk.END,
                "\n\nSIMULATION ERROR\n"
                "========================================\n"
                + self._worker_error
            )
            self.results.configure(
                state="disabled"
            )

            messagebox.showerror(
                "Simulation Error",
                self._worker_error
            )

            return

        self.system_badge.configure(
            text="●  MISSION COMPLETE",
            bg=SUCCESS_LIGHT,
            fg=SUCCESS
        )

        self._set_phase("COMPLETE")

        self.status.configure(
            text="Simulation completed successfully"
        )

        if Path(
            OUTPUT_FILE
        ).exists():
            self.plot_button.configure(
                state="normal"
            )

    # ========================================================
    # OPEN PLOTS
    # ========================================================

    def open_plots(self):

        try:
            code_dir = Path(__file__).resolve().parent
            plot_file = code_dir / "plot_model.py"
            csv_file = code_dir / OUTPUT_FILE

            if not plot_file.exists():
                raise FileNotFoundError(f"Plot model not found: {plot_file}")
            if not csv_file.exists():
                raise FileNotFoundError(f"Trajectory CSV not found: {csv_file}")

            kwargs = {"cwd": str(code_dir)}
            if sys.platform.startswith("win"):
                kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE

            subprocess.Popen([sys.executable, str(plot_file)], **kwargs)
            self.status.configure(text="Trajectory plots opened")

        except Exception as e:
            messagebox.showerror("Plot Error", str(e))


if __name__ == "__main__":

    root = tk.Tk()
    root.destroy()

    app = BalloonFlightGUI()
    app.root.mainloop()
