# master_runner.py
import json
import subprocess
import sys
import os
import time
import threading
import runpy
import shutil

# Pfad anpassen, damit die utils importiert werden können
from datetime import datetime, timezone
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = SCRIPT_DIR
sys.path.append(os.path.join(PROJECT_ROOT, 'src'))

# Ensure logs/optimizer_output.log always exists
LOGS_DIR = os.path.join(SCRIPT_DIR, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)
OPTIMIZER_LOG = os.path.join(LOGS_DIR, 'optimizer_output.log')
if not os.path.exists(OPTIMIZER_LOG):
    with open(OPTIMIZER_LOG, 'w', encoding='utf-8') as f:
        f.write("")

from utbot2.utils.exchange import Exchange


def _find_python_exec():
    candidates = [
        os.path.join(SCRIPT_DIR, '.venv', 'Scripts', 'python.exe'),
        os.path.join(SCRIPT_DIR, '.venv', 'bin', 'python3'),
        sys.executable,
        shutil.which('python3') or '',
        shutil.which('python') or ''
    ]
    checked = set()
    for c in candidates:
        if not c or c in checked:
            continue
        checked.add(c)
        if os.path.isabs(c) and os.path.exists(c):
            try:
                proc = subprocess.run([c, '-c', 'import sys; print(1)'],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                if proc.returncode == 0:
                    return c
            except Exception:
                continue
        else:
            found = shutil.which(c)
            if found:
                try:
                    proc = subprocess.run([found, '-c', 'import sys; print(1)'],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                    if proc.returncode == 0:
                        return found
                except Exception:
                    continue
    return None


def main():
    """
    Der Master Runner für den UtBot2.
    - Liest die settings.json, um den Modus (Autopilot/Manuell) zu bestimmen.
    - Prüft ob die Auto-Optimierung fällig ist und startet sie ggf. im Hintergrund.
    - Startet für jede als "active" markierte Strategie einen separaten run.py Prozess.
    """
    settings_file = os.path.join(SCRIPT_DIR, 'settings.json')
    optimization_results_file = os.path.join(SCRIPT_DIR, 'artifacts', 'results', 'optimization_results.json')
    bot_runner_script = os.path.join(SCRIPT_DIR, 'src', 'utbot2', 'strategy', 'run.py')
    secret_file = os.path.join(SCRIPT_DIR, 'secret.json')

    python_executable = _find_python_exec()
    if not python_executable:
        print("Fehler: Kein lauffähiger Python-Interpreter gefunden (.venv oder system python).")
        return

    print("=======================================================")
    print("UtBot2 Master Runner v2.0")
    print("=======================================================")

    # ----------------------
    # AUTO-OPTIMIZER STATUS
    # ----------------------
    try:
        auto_should_run = False
        auto_reason = 'unknown'
        scheduler_mod = None
        try:
            import auto_optimizer_scheduler as scheduler_mod
            last_run = None
            lr_path = os.path.join(SCRIPT_DIR, 'data', 'cache', '.last_optimization_run')
            if os.path.exists(lr_path):
                try:
                    last_run = datetime.fromisoformat(
                        open(lr_path, 'r', encoding='utf-8').read().strip())
                except Exception:
                    last_run = None
            with open(settings_file, 'r', encoding='utf-8') as _sf:
                sched_settings = json.load(_sf)
            do_run, reason = scheduler_mod.should_run(sched_settings, last_run, datetime.now())
            auto_should_run = bool(do_run)
            auto_reason = reason
        except Exception as e:
            print(f'INFO: Scheduler-Check nicht verfügbar: {e}')

        if auto_should_run:
            print(f"AUTOOPTIMIERUNG NÖTIG — Grund: {auto_reason}")
            print("Autooptimierung wird gestartet.")

            inprog_file = os.path.join(SCRIPT_DIR, 'data', 'cache', '.optimization_in_progress')

            # Stale-Marker bereinigen
            if os.path.exists(inprog_file) and scheduler_mod:
                try:
                    if scheduler_mod._is_stale_in_progress():
                        print('INFO: Staler In-Progress-Marker gefunden. Wird bereinigt...')
                        os.remove(inprog_file)
                except Exception:
                    pass

            # Scheduler starten wenn kein Optimizer läuft
            if not os.path.exists(inprog_file):
                scheduler_py = os.path.join(SCRIPT_DIR, 'auto_optimizer_scheduler.py')
                if os.path.exists(scheduler_py):
                    try:
                        py_exec = python_executable or 'python'
                        trigger_log = os.path.join(SCRIPT_DIR, 'logs', 'auto_optimizer_trigger.log')
                        os.makedirs(os.path.dirname(trigger_log), exist_ok=True)
                        with open(trigger_log, 'a', encoding='utf-8') as _lf:
                            proc = subprocess.Popen(
                                [py_exec, scheduler_py, '--force'],
                                cwd=SCRIPT_DIR,
                                stdout=_lf,
                                stderr=subprocess.STDOUT,
                                start_new_session=True
                            )
                            time.sleep(0.75)
                            if proc.poll() is None:
                                print(f'INFO: Scheduler gestartet (PID {proc.pid}).')
                            else:
                                print(f'WARN: Scheduler-Start schlug fehl (exit={proc.returncode}).')
                    except Exception as _e:
                        print(f'WARN: Scheduler-Auto-Start fehlgeschlagen: {_e}')
                        # Fallback: in-process
                        try:
                            def _run_inproc():
                                try:
                                    runpy.run_path(scheduler_py, run_name='__main__')
                                except Exception as ie:
                                    with open(trigger_log, 'a', encoding='utf-8') as _lf:
                                        _lf.write(f"INPROC-ERROR: {ie}\n")
                            t = threading.Thread(target=_run_inproc, daemon=True)
                            t.start()
                            time.sleep(0.5)
                            print('INFO: Scheduler (inproc) gestartet.')
                        except Exception as ie:
                            print(f'ERROR: In-proc fallback fehlgeschlagen: {ie}')
                else:
                    print('WARN: auto_optimizer_scheduler.py nicht gefunden.')
            else:
                print('INFO: Scheduler bereits aktiv (in-progress marker vorhanden).')
        else:
            if auto_reason and auto_reason != 'unknown':
                print(f'Auto-Optimizer: {auto_reason}')

    except Exception as _e:
        # non-fatal — continue with master runner
        print(f'WARN: Auto-Optimizer Check fehlgeschlagen: {_e}')

    # ----------------------
    # STRATEGIEN STARTEN
    # ----------------------
    try:
        with open(settings_file, 'r') as f:
            settings = json.load(f)

        with open(secret_file, 'r') as f:
            secrets = json.load(f)

        if not secrets.get('utbot2'):
            print("Fehler: Kein 'utbot2'-Account in secret.json gefunden.")
            return
        main_account_config = secrets['utbot2'][0]

        live_settings = settings.get('live_trading_settings', {})
        use_autopilot = live_settings.get('use_auto_optimizer_results', False)

        strategy_list = []
        if use_autopilot:
            print("Modus: Autopilot. Lese Strategien aus den Optimierungs-Ergebnissen...")
            with open(optimization_results_file, 'r') as f:
                strategy_config = json.load(f)
            strategy_list = strategy_config.get('optimal_portfolio', [])
        else:
            print("Modus: Manuell. Lese Strategien aus den manuellen Einstellungen...")
            strategy_list = live_settings.get('active_strategies', [])

        if not strategy_list:
            print("Keine aktiven Strategien zum Ausführen gefunden.")
            return

        print("=======================================================")

        for strategy_info in strategy_list:
            if isinstance(strategy_info, dict) and not strategy_info.get("active", True):
                symbol = strategy_info.get('symbol', 'N/A')
                timeframe = strategy_info.get('timeframe', 'N/A')
                print(f"\n--- Überspringe inaktive Strategie: {symbol} ({timeframe}) ---")
                continue

            symbol, timeframe, use_macd = None, None, None

            if use_autopilot and isinstance(strategy_info, str):
                pass

            elif isinstance(strategy_info, dict):
                symbol = strategy_info.get('symbol')
                timeframe = strategy_info.get('timeframe')
                use_macd = strategy_info.get('use_macd_filter', False)

            if not all([symbol, timeframe, use_macd is not None]):
                print(f"Warnung: Unvollständige Strategie-Info: {strategy_info}. Überspringe.")
                continue

            print(f"\n--- Starte Bot für: {symbol} ({timeframe}) ---")

            command = [
                python_executable,
                bot_runner_script,
                "--symbol", symbol,
                "--timeframe", timeframe,
                "--use_macd", str(use_macd)
            ]

            try:
                subprocess.Popen(command)
            except Exception as e:
                print(f"WARN: could not start bot with '{command[0]}': {e} — falling back to sys.executable")
                try:
                    fallback_cmd = [sys.executable, bot_runner_script,
                                    "--symbol", symbol, "--timeframe", timeframe,
                                    "--use_macd", str(use_macd)]
                    subprocess.Popen(fallback_cmd)
                except Exception as e2:
                    print(f"ERROR: fallback start also failed: {e2}")
            time.sleep(2)

        # --- Auto-Optimizer: Trigger falls last_run Cache fehlt ---
        try:
            opt_settings = settings.get('optimization_settings', {})
            if opt_settings.get('enabled', False):
                cache_file = os.path.join(SCRIPT_DIR, 'data', 'cache', '.last_optimization_run')
                inprog_file = os.path.join(SCRIPT_DIR, 'data', 'cache', '.optimization_in_progress')

                if scheduler_mod and os.path.exists(inprog_file):
                    try:
                        if scheduler_mod._is_stale_in_progress():
                            os.remove(inprog_file)
                    except Exception:
                        pass

                if auto_should_run and (not os.path.exists(cache_file)) and \
                   (not os.path.exists(inprog_file)):
                    print(f"INFO: {cache_file} fehlt — trigger Auto-Optimizer (forced).")
                    scheduler_py = os.path.join(SCRIPT_DIR, 'auto_optimizer_scheduler.py')
                    if os.path.exists(scheduler_py):
                        trigger_log = os.path.join(SCRIPT_DIR, 'logs', 'auto_optimizer_trigger.log')
                        os.makedirs(os.path.dirname(trigger_log), exist_ok=True)
                        try:
                            with open(trigger_log, 'a', encoding='utf-8') as _lf:
                                proc = subprocess.Popen(
                                    [python_executable, scheduler_py, '--force'],
                                    cwd=SCRIPT_DIR,
                                    stdout=_lf,
                                    stderr=subprocess.STDOUT,
                                    start_new_session=True
                                )
                            time.sleep(0.75)
                            if proc.poll() is None:
                                print(f'INFO: Scheduler (cache-missing) gestartet (PID {proc.pid}).')
                        except Exception as e:
                            print(f'WARN: Cache-missing Trigger fehlgeschlagen: {e}')
        except Exception as _e:
            print(f'WARN: Auto-Optimizer Cache-Trigger fehlgeschlagen: {_e}')

    except FileNotFoundError as e:
        print(f"Fehler: Eine wichtige Datei wurde nicht gefunden: {e}")
    except Exception as e:
        import traceback
        print(f"Ein unerwarteter Fehler im Master Runner ist aufgetreten: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
