#!/usr/bin/env python3
"""
Auto Optimizer Scheduler for UtBot2
- Reads `optimization_settings.schedule` from `settings.json` and decides whether
  to start `run_pipeline_automated.sh`.
- Usage:
    python auto_optimizer_scheduler.py --check-only    # only evaluate, don't run
    python auto_optimizer_scheduler.py --force         # force a run now
    python auto_optimizer_scheduler.py --daemon        # keep checking (default interval 300s)

Behavior:
- Uses `data/cache/.last_optimization_run` to remember the last run time.
- Will trigger when the scheduled time passed and the last run is older than
  the scheduled occurrence (respects interval settings).
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, date, time as dtime, timedelta, timezone

# HTTP helper for Telegram notifications
try:
    import requests
except Exception:
    requests = None

ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(ROOT, 'settings.json')
CACHE_DIR = os.path.join(ROOT, 'data', 'cache')
LAST_RUN_FILE = os.path.join(CACHE_DIR, '.last_optimization_run')
IN_PROGRESS_FILE = os.path.join(CACHE_DIR, '.optimization_in_progress')
PIPELINE_SCRIPT = os.path.join(ROOT, 'run_pipeline_automated.sh')

TRIGGER_LOG = os.path.join(ROOT, 'logs', 'auto_optimizer_trigger.log')


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    else:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m"


def _write_trigger_log(line: str) -> None:
    try:
        os.makedirs(os.path.dirname(TRIGGER_LOG), exist_ok=True)
        ts = datetime.now().isoformat()
        entry = f"{ts} {line}\n"

        with open(TRIGGER_LOG, 'a', encoding='utf-8') as f:
            f.write(entry)

        try:
            opt_log = os.path.join(ROOT, 'logs', 'optimizer_output.log')
            os.makedirs(os.path.dirname(opt_log), exist_ok=True)
            with open(opt_log, 'a', encoding='utf-8') as f2:
                f2.write(entry)
        except Exception:
            pass

        try:
            mr_log = os.path.join(ROOT, 'logs', 'master_runner_debug.log')
            os.makedirs(os.path.dirname(mr_log), exist_ok=True)
            with open(mr_log, 'a', encoding='utf-8') as f3:
                f3.write(entry)
        except Exception:
            pass

        print(entry.strip())
    except Exception:
        print(f"WARN: could not write trigger log: {line}")


def _set_in_progress() -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(IN_PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump({'pid': os.getpid(), 'started': datetime.now().isoformat()}, f)
        status_file = os.path.join(CACHE_DIR, '.optimization_status.json')
        try:
            with open(status_file, 'w', encoding='utf-8') as sf:
                json.dump({'status': 'starting', 'started_at': datetime.now().isoformat()}, sf)
        except Exception:
            pass
        print(f'DEBUG: wrote in-progress marker {IN_PROGRESS_FILE}')
    except Exception as e:
        print(f'WARN: could not write in-progress marker: {e}')


def _clear_in_progress() -> None:
    try:
        if os.path.exists(IN_PROGRESS_FILE):
            os.remove(IN_PROGRESS_FILE)
            print(f'DEBUG: cleared in-progress marker {IN_PROGRESS_FILE}')
        status_file = os.path.join(CACHE_DIR, '.optimization_status.json')
        try:
            if os.path.exists(status_file):
                os.remove(status_file)
        except Exception:
            pass
    except Exception as e:
        print(f'WARN: could not clear in-progress marker: {e}')


def _read_in_progress_ts() -> str | None:
    try:
        if os.path.exists(IN_PROGRESS_FILE):
            return open(IN_PROGRESS_FILE, 'r', encoding='utf-8').read().strip()
    except Exception:
        return None
    return None


def _is_stale_in_progress(max_hours: int = 24) -> bool:
    """Returns True if the in-progress marker is stale (process dead or too old)."""
    if not os.path.exists(IN_PROGRESS_FILE):
        return False
    try:
        content = open(IN_PROGRESS_FILE, 'r', encoding='utf-8').read().strip()
        try:
            data = json.loads(content)
            pid = data.get('pid')
            started = data.get('started', '')
        except (json.JSONDecodeError, ValueError):
            pid = None
            started = content

        if pid:
            try:
                os.kill(int(pid), 0)
                return False
            except (ProcessLookupError, OSError):
                return True

        # No PID stored: use pgrep to check for running scheduler
        try:
            import subprocess as _sp
            r = _sp.run(['pgrep', '-f', 'auto_optimizer_scheduler.py'],
                        capture_output=True, timeout=3)
            if r.returncode == 0:
                return False
            return True
        except Exception:
            pass

        # Final fallback: age check
        if started:
            try:
                started_dt = datetime.fromisoformat(started)
                age_hours = (datetime.now() - started_dt).total_seconds() / 3600
                return age_hours > max_hours
            except Exception:
                pass
        return True
    except Exception:
        return True


def load_settings() -> dict:
    with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def read_last_run() -> datetime | None:
    try:
        with open(LAST_RUN_FILE, 'r', encoding='utf-8') as f:
            text = f.read().strip()
            return datetime.fromisoformat(text)
    except Exception:
        return None


def write_last_run(ts: datetime) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(LAST_RUN_FILE, 'w', encoding='utf-8') as f:
        f.write(ts.isoformat())
    try:
        _write_trigger_log(f"AUTO-OPTIMIZER LAST_RUN updated={ts.isoformat()}")
    except Exception:
        pass


def _interval_to_minutes(schedule: dict) -> int:
    interval = schedule.get('interval', {})
    if interval and isinstance(interval, dict):
        value = int(interval.get('value', 0) or 0)
        unit = interval.get('unit', 'days').lower().rstrip('s')
        if unit in ('minute', 'min', 'm'):
            return value
        if unit in ('hour', 'h'):
            return value * 60
        if unit in ('day', 'd'):
            return value * 60 * 24
        if unit in ('week', 'w'):
            return value * 60 * 24 * 7
        return value * 60 * 24
    legacy = int(schedule.get('interval_days', 0) or 0)
    return legacy * 60 * 24


def compute_last_scheduled_datetime(schedule: dict, now: datetime) -> datetime:
    dow = schedule.get('day_of_week')
    hour = int(schedule.get('hour', 0))
    minute = int(schedule.get('minute', 0))

    if dow is None:
        scheduled_date = now.date()
    else:
        days_ago = (now.weekday() - int(dow)) % 7
        scheduled_date = (now - timedelta(days=days_ago)).date()

    return datetime.combine(scheduled_date, dtime(hour=hour, minute=minute))


def should_run(settings: dict, last_run: datetime | None, now: datetime) -> tuple[bool, str]:
    opt = settings.get('optimization_settings', {})
    if not opt.get('enabled', False):
        return False, 'optimization_settings.enabled is false'

    schedule = opt.get('schedule', {})
    interval_minutes = _interval_to_minutes(schedule)

    # Pure interval scheduling (< 1 day)
    if 0 < interval_minutes < 1440:
        if not last_run:
            return True, f'kein letzter Lauf (Intervall-Modus: {interval_minutes}min)'
        delta_minutes = (now - last_run).total_seconds() / 60
        if delta_minutes < interval_minutes:
            return False, f'zu frueh: {delta_minutes:.0f}min seit letztem Lauf < {interval_minutes}min'
        return True, f'interval={interval_minutes}min'

    # Calendar-based scheduling (day_of_week + hour)
    scheduled_dt = compute_last_scheduled_datetime(schedule, now)

    if now < scheduled_dt:
        return False, f'Next scheduled time not reached (scheduled={scheduled_dt.isoformat()})'

    if last_run and last_run >= scheduled_dt:
        return False, f'already ran for this scheduled occurrence (last_run={last_run.isoformat()})'

    if interval_minutes > 0 and last_run:
        delta_minutes = (now - last_run).total_seconds() / 60
        if delta_minutes < interval_minutes:
            delta_h = int(delta_minutes // 60)
            interval_h = int(interval_minutes // 60)
            return False, f'last run {delta_h}h ago < interval ({interval_h}h = {interval_minutes}min)'

    return True, f'should run (scheduled_dt={scheduled_dt.isoformat()}, interval={interval_minutes}min)'


def _send_telegram_message(text: str) -> bool:
    secret_path = os.path.join(ROOT, 'secret.json')
    try:
        with open(secret_path, 'r', encoding='utf-8') as f:
            sec = json.load(f)
        tg = sec.get('telegram', {})
        bot = tg.get('bot_token')
        chat = tg.get('chat_id')
        if not bot or not chat:
            print('INFO: Telegram not configured in secret.json (bot_token/chat_id missing)')
            return False
    except Exception as e:
        print(f'INFO: secret.json not available or unreadable: {e}')
        return False

    payload = {'chat_id': chat, 'text': text}
    url = f'https://api.telegram.org/bot{bot}/sendMessage'

    if requests:
        try:
            r = requests.post(url, data=payload, timeout=10)
            if r.status_code == 200:
                return True
            else:
                print(f'WARN: Telegram API returned status {r.status_code}: {r.text}')
                return False
        except Exception as e:
            print(f'WARN: Exception while sending Telegram message: {e}')
            return False
    else:
        try:
            subprocess.run(['curl', '-s', '-X', 'POST', url, '-d', f"chat_id={chat}",
                            '-d', f"text={text}"], check=False)
            return True
        except Exception as e:
            print(f'WARN: Could not send Telegram message (curl fallback failed): {e}')
            return False


def _resolve_symbols_auto(settings: dict) -> list[str]:
    """Auto-detect symbols: scan CSV cache files first, fall back to active_strategies."""
    import glob as _glob
    # Try to find cached OHLCV files (e.g. BTC-USDT-USDT_15m.csv)
    files = _glob.glob(os.path.join(CACHE_DIR, '*-USDT-USDT_*.csv'))
    found = set()
    for f in files:
        m = re.search(r'([A-Z0-9]+)-USDT-USDT_', os.path.basename(f))
        if m:
            found.add(m.group(1))
    if found:
        return sorted(found)

    # Fall back to active_strategies in settings
    strats = settings.get('live_trading_settings', {}).get('active_strategies', [])
    symbols = []
    seen = set()
    for s in strats:
        if not s.get('active', True):
            continue
        sym = s.get('symbol', '')
        base = sym.split('/')[0] if '/' in sym else sym
        if base and base not in seen:
            seen.add(base)
            symbols.append(base)
    return symbols if symbols else ['BTC', 'ETH', 'SOL', 'XRP', 'AAVE']


def _resolve_timeframes_auto(settings: dict) -> list[str]:
    """Auto-detect timeframes from active_strategies."""
    strats = settings.get('live_trading_settings', {}).get('active_strategies', [])
    timeframes = []
    seen = set()
    for s in strats:
        if not s.get('active', True):
            continue
        tf = s.get('timeframe', '')
        if tf and tf not in seen:
            seen.add(tf)
            timeframes.append(tf)
    return timeframes if timeframes else ['15m', '1h', '6h', '1d']


def run_pipeline() -> int:
    """Execute run_pipeline_automated.sh, falling back to direct Python invocation."""
    opt_log = os.path.join(ROOT, 'logs', 'optimizer_output.log')
    os.makedirs(os.path.dirname(opt_log), exist_ok=True)

    # --- Primary: bash pipeline ---
    if os.path.exists(PIPELINE_SCRIPT):
        bash_cmd = None

        def _bash_cd_ok(path_candidate: str) -> bool:
            try:
                rc = subprocess.run(['bash', '-lc', f"cd '{path_candidate}' && pwd"],
                                    shell=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                return rc.returncode == 0
            except Exception:
                return False

        if os.name == 'nt':
            from pathlib import Path
            p = Path(ROOT)
            drive = p.drive.rstrip(':').lower() if p.drive else ''
            rest = p.as_posix().split(':', 1)[-1] if ':' in p.as_posix() else p.as_posix()
            candidates = []
            if drive:
                candidates.append(f"/mnt/{drive}{rest}")
                candidates.append(f"/{drive}{rest}")
            candidates.append(ROOT)

            for c in candidates:
                if _bash_cd_ok(c):
                    bash_cmd = ['bash', '-lc', f"cd '{c}' && ./run_pipeline_automated.sh"]
                    print(f'INFO: using bash cd candidate: {c}')
                    break
        else:
            bash_cmd = ['bash', '-lc', f"cd '{ROOT}' && ./run_pipeline_automated.sh"]

        if bash_cmd:
            print(f'Running pipeline: {bash_cmd}')
            _write_trigger_log(f"AUTO-OPTIMIZER PIPELINE_EXEC method=bash cmd={bash_cmd}")
            try:
                proc = subprocess.Popen(bash_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        cwd=ROOT, universal_newlines=True, bufsize=1)
                with open(opt_log, 'a', encoding='utf-8') as _out:
                    for ln in proc.stdout:
                        try:
                            _out.write(ln)
                            _out.flush()
                        except Exception:
                            pass
                        try:
                            print(ln.rstrip())
                        except Exception:
                            pass
                    proc.wait()
                    rc = proc.returncode

                print(f'Pipeline exited with return code: {rc}')
                _write_trigger_log(f"AUTO-OPTIMIZER PIPELINE_EXIT rc={rc}")

                if rc == 0:
                    return rc
                _write_trigger_log('AUTO-OPTIMIZER PIPELINE_WARNING Bash exit != 0 — attempting Python fallback')
                print('WARN: Bash pipeline failed — attempting direct Python fallback')
            except FileNotFoundError:
                _write_trigger_log('AUTO-OPTIMIZER PIPELINE_FALLBACK method=python (bash not found)')
                print('WARN: bash not found on PATH — using Python fallback')
            except Exception as e:
                print(f'ERROR: Exception while running bash pipeline: {e}')
                _write_trigger_log(f'AUTO-OPTIMIZER PIPELINE_ERROR {e}')

    # --- Fallback: direct Python invocation ---
    try:
        settings = load_settings()
        opt = settings.get('optimization_settings', {})

        # Resolve symbols
        syms_cfg = opt.get('symbols_to_optimize', 'auto')
        if isinstance(syms_cfg, list):
            symbols_arg = ' '.join(syms_cfg)
        elif str(syms_cfg).lower() == 'auto':
            symbols_arg = ' '.join(_resolve_symbols_auto(settings))
        else:
            symbols_arg = str(syms_cfg)

        # Resolve timeframes
        tfs_cfg = opt.get('timeframes_to_optimize', 'auto')
        if isinstance(tfs_cfg, list):
            timeframes_arg = ' '.join(tfs_cfg)
        elif str(tfs_cfg).lower() == 'auto':
            timeframes_arg = ' '.join(_resolve_timeframes_auto(settings))
        else:
            timeframes_arg = str(tfs_cfg)

        # Date range
        yesterday = datetime.now() - timedelta(days=1)
        end_date = yesterday.strftime('%Y-%m-%d')
        start_date = 'auto'

        # Optimizer parameters
        jobs = int(opt.get('cpu_cores', -1))
        trials = int(opt.get('num_trials', 10))
        constraints = opt.get('constraints', {})
        max_dd = float(constraints.get('max_drawdown_pct', 30))
        min_wr = float(constraints.get('min_win_rate_pct', 55))
        min_pnl = float(constraints.get('min_pnl_pct', 0))
        start_capital = float(opt.get('start_capital', 1000))
        mode = 'strict'

        optimizer_py = os.path.join(ROOT, 'src', 'utbot2', 'analysis', 'optimizer.py')
        if not os.path.exists(optimizer_py):
            print(f'ERROR: optimizer.py not found at {optimizer_py}')
            return 2

        # Find Python interpreter
        venv_py_win = os.path.join(ROOT, '.venv', 'Scripts', 'python.exe')
        venv_py_unix = os.path.join(ROOT, '.venv', 'bin', 'python3')
        if os.path.exists(venv_py_win):
            python_exec = venv_py_win
        elif os.path.exists(venv_py_unix):
            python_exec = venv_py_unix
        else:
            python_exec = sys.executable or 'python'

        cmd = [python_exec, '-u', optimizer_py,
               '--symbols', symbols_arg,
               '--timeframes', timeframes_arg,
               '--start_date', start_date,
               '--end_date', end_date,
               '--jobs', str(jobs),
               '--max_drawdown', str(max_dd),
               '--start_capital', str(start_capital),
               '--min_win_rate', str(min_wr),
               '--trials', str(trials),
               '--min_pnl', str(min_pnl),
               '--mode', mode]

        print(f'Running direct Python optimizer: {python_exec}')
        print(f'Symbole: {symbols_arg} | Timeframes: {timeframes_arg}')
        _write_trigger_log(f"AUTO-OPTIMIZER FALLBACK method=python interpreter={python_exec}")

        with open(opt_log, 'a', encoding='utf-8') as _out:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    universal_newlines=True)
            for ln in proc.stdout:
                try:
                    _out.write(ln)
                    _out.flush()
                except Exception:
                    pass
                try:
                    print(ln.rstrip())
                except Exception:
                    pass
            proc.wait()
            _write_trigger_log(f"AUTO-OPTIMIZER PIPELINE_EXIT rc={proc.returncode}")
            return proc.returncode

    except Exception as e:
        print(f'ERROR: Python fallback failed: {e}')
        return 4


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument('--check-only', action='store_true', help="Only evaluate scheduler (don't run)")
    p.add_argument('--force', action='store_true', help="Force a run now and update last-run timestamp")
    p.add_argument('--daemon', action='store_true', help="Run scheduler loop")
    p.add_argument('--interval', type=int, default=300, help="Daemon sleep interval in seconds")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    now = datetime.now()

    try:
        settings = load_settings()
    except Exception as e:
        print(f'ERROR: cannot load settings.json: {e}')
        return 3

    def check_and_maybe_run(force: bool = False) -> None:
        nonlocal now
        now = datetime.now()
        last_run = read_last_run()

        if not force:
            sr, reason = should_run(settings, last_run, now)
            if not sr:
                print(f'Scheduler: skip — {reason}')
                return
            print(f'Scheduler: trigger — {reason}')

        schedule = settings.get('optimization_settings', {}).get('schedule', {})
        _write_trigger_log(f"AUTO-OPTIMIZER START reason={'forced' if force else 'scheduled'} "
                           f"scheduled={schedule} last_run={last_run}")
        print(f"{'Force run' if force else 'Scheduled run'} -> executing optimizer now")

        notify = settings.get('optimization_settings', {}).get('send_telegram_on_completion', False)

        _set_in_progress()
        start_notify_file = os.path.join(CACHE_DIR, '.optimization_start_notified')
        try:
            if os.path.exists(start_notify_file):
                os.remove(start_notify_file)
        except Exception:
            pass

        if notify:
            try:
                live_strats = settings.get('live_trading_settings', {}).get('active_strategies', [])
                start_pairs = [f"{s['symbol'].split('/')[0]}/{s['timeframe']}"
                               for s in live_strats if s.get('active', True)]
            except Exception:
                start_pairs = []
            _trials_n = settings.get('optimization_settings', {}).get('num_trials', '?')
            _pairs_str = ', '.join(start_pairs) if start_pairs else 'auto'
            start_msg = (
                f"🚀 UtBot2 Auto-Optimizer GESTARTET\n"
                f"Paare: {_pairs_str}\n"
                f"Trials: {_trials_n}\n"
                f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            sent = _send_telegram_message(start_msg)
            if not sent:
                try:
                    import time as _time
                    _time.sleep(3)
                    sent = _send_telegram_message(start_msg + ' (retry)')
                except Exception:
                    sent = False
            if sent:
                try:
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    with open(start_notify_file, 'w', encoding='utf-8') as _sn:
                        _sn.write(datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
                except Exception:
                    pass
            else:
                _write_trigger_log('AUTO-OPTIMIZER NOTIFY start result=failed')

        start_ts = datetime.now()
        try:
            rc = run_pipeline()
        finally:
            _clear_in_progress()

        elapsed = (datetime.now() - start_ts).total_seconds()

        if rc == 0:
            write_last_run(datetime.now())
            _write_trigger_log(f"AUTO-OPTIMIZER FINISH result=success elapsed_s={elapsed:.1f}")
            print('Optimizer finished successfully; updated last-run timestamp.')
            if notify:
                dur_str = _format_duration(int(elapsed))
                comp_msg = f"✅ UtBot2 Auto-Optimizer abgeschlossen (Dauer: {dur_str})"
                _send_telegram_message(comp_msg)
        else:
            _write_trigger_log(f"AUTO-OPTIMIZER FINISH result=error code={rc} elapsed_s={elapsed:.1f}")
            print(f'Optimizer exited with return code {rc}')
            if notify:
                _send_telegram_message(f'❌ UtBot2 Automatische Optimierung ist mit Fehlercode {rc} beendet.')

        try:
            if os.path.exists(start_notify_file):
                os.remove(start_notify_file)
        except Exception:
            pass

    if args.check_only:
        last_run = read_last_run()
        sr, reason = should_run(settings, last_run, now)
        print(f"should_run={sr} reason={reason}")
        return 0

    if args.force:
        check_and_maybe_run(force=True)
        return 0

    if args.daemon:
        print('Starting scheduler daemon... (use Ctrl-C to stop)')
        try:
            while True:
                check_and_maybe_run(force=False)
                import time as _time
                _time.sleep(args.interval)
        except KeyboardInterrupt:
            print('Scheduler daemon stopped by user')
            return 0

    # default: single check
    check_and_maybe_run(force=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
