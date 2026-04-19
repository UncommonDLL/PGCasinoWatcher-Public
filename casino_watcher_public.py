#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.arena_tracker import (
    ArenaTracker,
    FightResult,
    LearnedPatternStore,
    MatchState,
    find_latest_log,
    parse_log_line,
)
from shared.fighter_norm import normalize_fighter_name, normalize_matchup_pair

VERSION = "1.1.2-public"

def setup_logging(log_file: Optional[Path], verbose: bool) -> logging.Logger:
    logger = logging.getLogger("casino_watcher")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    if logger.handlers:
        for handler in logger.handlers:
            handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    logger.propagate = False
    return logger

_PG_CHATLOG_RELATIVE = (
    "AppData", "LocalLow", "Elder Game", "Project Gorgon", "ChatLogs"
)

def discover_chatlog_dir() -> Optional[Path]:
    user_profile = os.environ.get("USERPROFILE")
    if not user_profile:
        return None
    candidate = Path(user_profile).joinpath(*_PG_CHATLOG_RELATIVE)
    if candidate.is_dir():
        return candidate
    return None

def find_newest_chatlog(chatlog_dir: Path) -> Optional[Path]:
    candidates = sorted(
        chatlog_dir.glob("Chat-*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None

class ChatLogSource:
    __slots__ = ("path", "source", "log_file", "error")

    def __init__(self, path: Optional[Path], source: str,
                 log_file: Optional[Path], error: Optional[str]):
        self.path = path
        self.source = source
        self.log_file = log_file
        self.error = error

    @property
    def ok(self) -> bool:
        return self.path is not None and self.log_file is not None

def resolve_chatlog_source(
    config_override: str,
    saved_path: str,
) -> ChatLogSource:

    def _try_dir(candidate: Path, source: str) -> Optional[ChatLogSource]:
        if not candidate.is_dir():
            return ChatLogSource(
                path=None, source=source, log_file=None,
                error=f"Directory does not exist: {candidate}",
            )
        newest = find_newest_chatlog(candidate)
        if newest is None:
            return ChatLogSource(
                path=candidate, source=source, log_file=None,
                error="Directory exists but contains no Chat-*.log files.",
            )
        return ChatLogSource(path=candidate, source=source, log_file=newest, error=None)

    if config_override:
        return _try_dir(Path(config_override), "config")

    if saved_path:
        result = _try_dir(Path(saved_path), "saved")
        if result.ok:
            return result

    auto = discover_chatlog_dir()
    if auto is not None:
        return _try_dir(auto, "auto")

    return ChatLogSource(
        path=None, source="auto", log_file=None,
        error="Could not find Project Gorgon ChatLogs directory.",
    )

def _try_gui_folder_picker() -> Optional[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(
            title="Select Project Gorgon ChatLogs folder",
        )
        root.destroy()
        if folder:
            return folder
    except Exception:
        pass
    return None

def _prompt_manual_path() -> Optional[str]:
    print("\n  Enter the full path to your ChatLogs folder\n  (or press Enter to go back):\n")
    try:
        raw = input("  > ").strip().strip('"')
    except (EOFError, KeyboardInterrupt):
        return None
    return raw if raw else None

def _validate_chosen_folder(folder: str) -> Tuple[bool, str]:
    p = Path(folder)
    if not p.is_dir():
        return False, f"Not a valid directory: {folder}"
    logs = list(p.glob("Chat-*.log"))
    if not logs:
        return False, f"Directory exists but contains no Chat-*.log files:\n  {folder}"
    return True, f"Found {len(logs)} log file(s) in: {folder}"

def run_recovery_loop(state) -> Optional[Path]:
    print("\n" + "=" * 56)
    print("  CHATLOG SOURCE NOT FOUND")
    print("=" * 56 + "\n")
    
    while True:
        print("-" * 56)
        print("  [R] Retry auto-detection scan")
        print("  [C] Choose folder manually")
        print("  [Q] Quit\n")
        try:
            choice = input("  Choice: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            return None

        if choice == "Q":
            return None

        if choice == "R":
            source = resolve_chatlog_source(
                config_override="",
                saved_path=state.saved_chatlog_dir,
            )
            if source.ok:
                print(f"\n  Found: {source.path} (via {source.source})")
                return source.path
            print("\n  Still not found.\n")
            continue

        if choice == "C":
            print("\n  Opening folder picker...")
            folder = _try_gui_folder_picker()
            if folder:
                ok, msg = _validate_chosen_folder(folder)
                if ok:
                    print(f"\n  {msg}")
                    return Path(folder)
                else:
                    print(f"\n  {msg}")
            else:
                manual = _prompt_manual_path()
                if manual:
                    ok, msg = _validate_chosen_folder(manual)
                    if ok:
                        print(f"\n  {msg}")
                        return Path(manual)
                    else:
                        print(f"\n  {msg}")
            print()
            continue

        print("  Invalid choice. Please enter R, C, or Q.\n")

@dataclass
class Config:
    chatlog_dir: str = ""
    intake_url: str = ""
    state_file: str = "casino_watcher_state.json"
    log_file: str = "casino_watcher.log"
    learned_patterns_file: str = "learned_kuzavek_patterns.json"
    unmatched_log: str = "unmatched_kuzavek_lines.log"
    poll_seconds: float = 0.75
    start_mode: str = "end"
    max_retries: int = 5
    retry_base_delay: float = 2.0
    queue_flush_interval: float = 30.0
    contributor_name: str = ""
    near_duplicate_window_seconds: int = 3

    @staticmethod
    def load(path: Path) -> "Config":
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        cfg = Config()
        for key, val in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, val)
        return cfg

    def validate(self) -> List[str]:
        errors = []
        if not self.intake_url:
            errors.append("intake_url is required")
        if self.near_duplicate_window_seconds < 0:
            errors.append("near_duplicate_window_seconds must be >= 0")
        return errors

def make_dedupe_key(result: FightResult) -> str:
    norm_a, norm_b = normalize_matchup_pair(result.fighter_a, result.fighter_b)
    norm_w = normalize_fighter_name(result.winner)
    raw = f"{result.match_timestamp}|{norm_a}|{norm_b}|{norm_w}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

class IntakeClient:
    def __init__(self, intake_url: str, max_retries: int = 5,
                 retry_base_delay: float = 2.0,
                 contributor_name: str = "",
                 logger: Optional[logging.Logger] = None):
        self.intake_url = intake_url
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.contributor_name = contributor_name
        self.log = logger or logging.getLogger("casino_watcher")

    def health_check(self) -> bool:
        try:
            req = urllib.request.Request(self.intake_url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                data = json.loads(body)
                return data.get("ok", False)
        except Exception:
            return False

    def submit(self, result: FightResult, dedupe_key: str,
               dry_run: bool = False) -> bool:
        norm_a, norm_b = normalize_matchup_pair(result.fighter_a, result.fighter_b)
        norm_w = normalize_fighter_name(result.winner)

        payload = {
            "version": VERSION,
            "dedupe_key": dedupe_key,
            "match_timestamp": result.match_timestamp,
            "fighter_a": norm_a,
            "fighter_b": norm_b,
            "winner": norm_w,
            "method": result.method,
            "contributor": self.contributor_name,
        }

        if dry_run:
            self.log.info(f"[DRY RUN] Would submit: {norm_a} vs {norm_b} -> {norm_w} "
                          f"(key={dedupe_key})")
            return True

        data = json.dumps(payload).encode("utf-8")
        delay = self.retry_base_delay

        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(
                    self.intake_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    try:
                        resp_data = json.loads(body)
                    except Exception:
                        resp_data = {}
                    if resp_data.get("ok"):
                        return True
                    return True  
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    return True  
            except Exception as exc:
                pass

            if attempt < self.max_retries:
                time.sleep(delay)
                delay = min(delay * 2, 60)

        return False

class WatcherState:
    def __init__(self, path: Path):
        self.path = path
        self.offsets: dict = {}
        self.seen_keys: Set[str] = set()
        self.pending: List[dict] = []
        self.saved_chatlog_dir: str = ""
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.offsets = data.get("offsets", {})
            self.seen_keys = set(data.get("seen_keys", []))
            self.pending = data.get("pending", [])
            self.saved_chatlog_dir = data.get("saved_chatlog_dir", "")
        except Exception:
            pass

    def save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        keys_list = sorted(self.seen_keys)
        if len(keys_list) > 10000:
            keys_list = keys_list[-10000:]
            self.seen_keys = set(keys_list)
        data = {
            "offsets": self.offsets,
            "seen_keys": keys_list,
            "pending": self.pending,
            "saved_chatlog_dir": self.saved_chatlog_dir,
        }
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def is_duplicate(self, dedupe_key: str) -> bool:
        return dedupe_key in self.seen_keys

    def mark_seen(self, dedupe_key: str) -> None:
        self.seen_keys.add(dedupe_key)

    def queue_result(self, result: FightResult, dedupe_key: str) -> None:
        if not any(p.get("dedupe_key") == dedupe_key for p in self.pending):
            self.pending.append({
                "match_timestamp": result.match_timestamp,
                "fighter_a": result.fighter_a,
                "fighter_b": result.fighter_b,
                "winner": result.winner,
                "method": result.method,
                "source_text": result.source_text,
                "dedupe_key": dedupe_key,
            })

    def get_offset(self, log_file: str) -> int:
        return self.offsets.get(log_file, 0)

    def set_offset(self, log_file: str, offset: int) -> None:
        self.offsets[log_file] = offset

def print_preflight(
    chatlog_source: ChatLogSource,
    config: Config,
    dry_run: bool,
    log: logging.Logger,
) -> None:
    log.info("=" * 56)
    log.info("  CasinoWatcher Public  v%s", VERSION)
    log.info("=" * 56)
    log.info("")

    if chatlog_source.ok:
        log.info("  ChatLogs path : %s", chatlog_source.path)
    else:
        log.error("  ChatLogs path : NOT FOUND")

    if dry_run:
        log.info("  Mode          : DRY RUN")
    else:
        log.info("  Mode          : LIVE")

    if config.intake_url:
        log.info("  Intake URL    : CONFIGURED")
    else:
        log.warning("  Intake URL    : NOT CONFIGURED")

    log.info("")

class CasinoWatcher:
    def __init__(self, config: Config, chatlog_dir: Path,
                 dry_run: bool = False, verbose: bool = False):
        self.config = config
        self.chatlog_dir = chatlog_dir
        self.dry_run = dry_run
        self.verbose = verbose
        self.log = logging.getLogger("casino_watcher")
        self.state = WatcherState(Path(config.state_file))
        self.client = IntakeClient(
            intake_url=config.intake_url,
            max_retries=config.max_retries,
            retry_base_delay=config.retry_base_delay,
            contributor_name=config.contributor_name,
            logger=self.log,
        )
        self.learned_path = Path(config.learned_patterns_file) if config.learned_patterns_file else None
        self.unmatched_path = Path(config.unmatched_log) if config.unmatched_log else None
        self._last_queue_flush = 0.0
        self.recent_fights: dict[str, datetime] = {}

    def _make_tracker(self, current_dict: Optional[dict] = None) -> ArenaTracker:
        learned = LearnedPatternStore(self.learned_path)
        if current_dict:
            try:
                return ArenaTracker(
                    current=MatchState(**current_dict),
                    verbose=self.verbose,
                    unmatched_path=self.unmatched_path,
                    learned_patterns=learned,
                )
            except Exception:
                pass
        return ArenaTracker(
            verbose=self.verbose,
            unmatched_path=self.unmatched_path,
            learned_patterns=learned,
        )

    def _recent_fight_key(self, result: FightResult) -> str:
        norm_a, norm_b = normalize_matchup_pair(result.fighter_a, result.fighter_b)
        pair = tuple(sorted((norm_a, norm_b)))
        norm_w = normalize_fighter_name(result.winner)
        return f"{pair[0]}|{pair[1]}|{norm_w}"

    def _prune_recent_fights(self, reference_time: datetime) -> None:
        keep_seconds = max(30, self.config.near_duplicate_window_seconds * 10)
        cutoff = reference_time.timestamp() - keep_seconds
        self.recent_fights = {
            key: ts for key, ts in self.recent_fights.items()
            if ts.timestamp() >= cutoff
        }

    def _is_recent_duplicate(self, result: FightResult) -> bool:
        if self.config.near_duplicate_window_seconds <= 0:
            return False

        try:
            ts = datetime.strptime(result.match_timestamp, "%y-%m-%d %H:%M:%S")
        except ValueError:
            return False

        self._prune_recent_fights(ts)
        key = self._recent_fight_key(result)
        last_ts = self.recent_fights.get(key)

        if last_ts is not None:
            delta = abs((ts - last_ts).total_seconds())
            if delta <= self.config.near_duplicate_window_seconds:
                return True

        self.recent_fights[key] = ts
        return False

    def _handle_result(self, result: FightResult) -> None:
        if self._is_recent_duplicate(result):
            return

        dedupe_key = make_dedupe_key(result)

        if self.state.is_duplicate(dedupe_key):
            return

        submitted = self.client.submit(result, dedupe_key, dry_run=self.dry_run)
        if submitted:
            self.state.mark_seen(dedupe_key)
        else:
            self.state.queue_result(result, dedupe_key)
        self.state.save()

    def _flush_queue(self) -> None:
        if not self.state.pending:
            return
        remaining = []
        for item in self.state.pending:
            dedupe_key = item["dedupe_key"]
            if self.state.is_duplicate(dedupe_key):
                continue
            result = FightResult(
                match_timestamp=item["match_timestamp"],
                fighter_a=item["fighter_a"],
                fighter_b=item["fighter_b"],
                winner=item["winner"],
                method=item.get("method", "queued_retry"),
                source_text=item.get("source_text", ""),
            )
            if self.client.submit(result, dedupe_key, dry_run=self.dry_run):
                self.state.mark_seen(dedupe_key)
            else:
                remaining.append(item)
        self.state.pending = remaining
        self.state.save()

    def run(self) -> None:
        log_path = self.chatlog_dir
        self.log.info("Watching for fights. Press Ctrl+C to stop.")

        active_log: Optional[Path] = None
        file_handle = None
        tracker: Optional[ArenaTracker] = None

        try:
            while True:
                now = time.time()
                if now - self._last_queue_flush >= self.config.queue_flush_interval:
                    self._last_queue_flush = now
                    self._flush_queue()

                try:
                    latest = find_latest_log(log_path)
                except FileNotFoundError as exc:
                    self.log.error("[ERROR] %s", exc)
                    time.sleep(5)
                    continue

                if active_log != latest:
                    if file_handle:
                        file_handle.close()
                    active_log = latest
                    tracker = self._make_tracker()
                    offset = self.state.get_offset(str(active_log))
                    file_size = active_log.stat().st_size
                    if offset > file_size:
                        offset = 0
                    if offset == 0 and self.config.start_mode == "end":
                        offset = file_size
                    file_handle = active_log.open("rb")
                    file_handle.seek(offset)

                line = file_handle.readline()
                if not line:
                    time.sleep(self.config.poll_seconds)
                    continue

                pos_after = file_handle.tell()
                ts, text = parse_log_line(line)
                if ts and text:
                    results = tracker.feed(ts, text)
                    for result in results:
                        self._handle_result(result)

                self.state.set_offset(str(active_log), pos_after)
                self.state.save()

        except KeyboardInterrupt:
            self.log.info("Stopped by user.")
        finally:
            if file_handle:
                file_handle.close()
            self.state.save()

def main():
    parser = argparse.ArgumentParser()
    if getattr(sys, "frozen", False):
        default_config = Path(sys.executable).with_name("config.json")
    else:
        default_config = Path(__file__).resolve().parent.parent / "config.json"

    parser.add_argument("--config", default=str(default_config))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"CasinoWatcher Public v{VERSION}")
    args = parser.parse_args()

    try:
        config = Config.load(Path(args.config))
    except Exception as exc:
        print(f"[ERROR] Could not load config: {exc}")
        return 1

    errors = config.validate()
    if errors:
        for e in errors:
            print(f"[CONFIG ERROR] {e}")
        return 1

    log = setup_logging(
        Path(config.log_file) if config.log_file else None,
        args.verbose,
    )

    state = WatcherState(Path(config.state_file))
    chatlog_source = resolve_chatlog_source(
        config_override=config.chatlog_dir,
        saved_path=state.saved_chatlog_dir,
    )

    print_preflight(chatlog_source, config, args.dry_run, log)

    if not chatlog_source.ok:
        recovered_path = run_recovery_loop(state)
        if recovered_path is None:
            log.info("User chose to quit.")
            return 1
        chatlog_source = resolve_chatlog_source(
            config_override=str(recovered_path),
            saved_path="",
        )
        if not chatlog_source.ok:
            return 1

    state.saved_chatlog_dir = str(chatlog_source.path)
    state.save()

    if not args.dry_run and config.intake_url:
        client = IntakeClient(
            intake_url=config.intake_url,
            logger=log,
        )
        if client.health_check():
            log.info("  Intake health  : OK")
        else:
            log.warning("  Intake health  : UNREACHABLE")
    log.info("")

    watcher = CasinoWatcher(
        config=config,
        chatlog_dir=chatlog_source.path,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    watcher.state = state
    watcher.log = log
    watcher.client = IntakeClient(
        intake_url=config.intake_url,
        max_retries=config.max_retries,
        retry_base_delay=config.retry_base_delay,
        contributor_name=config.contributor_name,
        logger=log,
    )
    watcher.run()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())