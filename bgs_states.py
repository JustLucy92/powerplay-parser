"""Looks up BGS states from EDSM for the 'BGS States' column of the priority sheet.

auto_capture.py starts the lookup in a background thread while it takes screenshots and
leaves the result in OUTPUT_FILE; update_google_sheet.py attaches it to the upload.

Cell format: "<first-slot states or None> | Pending: ... | Other: ... | 2nd: ..."
Only the controlling faction is shown, plus first-slot states of a secondary faction
that owns a large-pad port which buys mined goods.
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

EDSM_FACTIONS_URL = 'https://www.edsm.net/api-system-v1/factions'
EDSM_STATIONS_URL = 'https://www.edsm.net/api-system-v1/stations'
OUTPUT_FILE = os.path.join('auto_capture_outputs', 'bgs_states.json')

MAX_AGE = timedelta(hours=12)   # ignore a lookup left over from an earlier run
REQUEST_DELAY = 1.0             # seconds between EDSM requests
REQUEST_TIMEOUT = 15
TOTAL_BUDGET = 300              # seconds; stop and keep what we have after this

FIRST_SLOT_STATES = {'boom', 'bust', 'investment', 'expansion', 'civil liberty'}
LARGE_PORT_TYPES = {'coriolis starport', 'orbis starport', 'ocellus starport',
                    'asteroid base', 'planetary port'}
MINED_GOODS_ECONOMIES = {'industrial', 'refinery', 'high tech', 'tourism'}


DISPLAY_NAMES = {'civil liberty': 'Civil Liberty'}   # EDSM sends "Civil liberty"; the sheet says "Civil Liberty"


def _states(faction, key):
    return [DISPLAY_NAMES.get(s['state'].lower(), s['state'])
            for s in faction.get(key) or [] if s.get('state')]


def _is_first_slot(state):
    return state.lower() in FIRST_SLOT_STATES


def _faction_names_with_first_slot_states(data, controller):
    return {f['name'] for f in data.get('factions') or []
            if f.get('name') != controller
            and any(_is_first_slot(s) for s in _states(f, 'activeStates'))}


def _good_port_owners(stations):
    """Names of factions controlling a large-pad port with a market in a mined-goods economy."""
    owners = set()
    for st in stations or []:
        faction = (st.get('controllingFaction') or {}).get('name')
        economies = {str(st.get('economy') or '').lower(), str(st.get('secondEconomy') or '').lower()}
        if (faction and st.get('haveMarket')
                and str(st.get('type') or '').lower() in LARGE_PORT_TYPES
                and economies & MINED_GOODS_ECONOMIES):
            owners.add(faction)
    return owners


def format_bgs_states(data, stations=None):
    """Build the cell text from an EDSM factions response (None if there is nothing to say)."""
    if not isinstance(data, dict):
        return None
    controller = (data.get('controllingFaction') or {}).get('name')
    factions = data.get('factions') or []
    faction = next((f for f in factions if f.get('name') == controller), None)
    if not controller or faction is None:
        return None

    active = _states(faction, 'activeStates')
    pending = _states(faction, 'pendingStates')
    first = [s for s in active if _is_first_slot(s)]
    other = [s for s in active if not _is_first_slot(s)]

    text = ', '.join(first) or 'None'
    if pending:
        text += ' | Pending: ' + ', '.join(pending)
    if other:
        text += ' | Other: ' + ', '.join(other)

    owners = _good_port_owners(stations) - {controller}
    second = []
    for f in factions:
        if f.get('name') in owners:
            for s in _states(f, 'activeStates'):
                if _is_first_slot(s) and s not in second:
                    second.append(s)
    if second:
        text += ' | 2nd: ' + ', '.join(second)
    return text


def _get_json(url, system_name):
    resp = requests.get(url, params={'systemName': system_name, 'showHistory': 0},
                        headers={'User-Agent': 'powerplay-parser'}, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 429:
        raise _RateLimited()
    resp.raise_for_status()
    return resp.json()


class _RateLimited(Exception):
    pass


def fetch_bgs_states(system_names, budget=TOTAL_BUDGET):
    """Returns {lowercase system name: cell text}. Never raises; failures just leave gaps."""
    states = {}
    start = time.monotonic()
    for name in system_names:
        if time.monotonic() - start > budget:
            break
        try:
            data = _get_json(EDSM_FACTIONS_URL, name)
            stations = None
            if isinstance(data, dict):
                controller = (data.get('controllingFaction') or {}).get('name')
                if _faction_names_with_first_slot_states(data, controller):
                    time.sleep(REQUEST_DELAY)
                    stations = (_get_json(EDSM_STATIONS_URL, name) or {}).get('stations')
            text = format_bgs_states(data, stations)
            if text is not None:
                states[name.lower()] = text
        except _RateLimited:
            break
        except (requests.RequestException, ValueError, AttributeError):
            pass
        time.sleep(REQUEST_DELAY)
    return states


def _worker(system_names, path):
    try:
        states = fetch_bgs_states(system_names)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'fetched_at': datetime.now(timezone.utc).isoformat(), 'states': states},
                      f, indent=1, ensure_ascii=False)
        print(f"\n[BGS] EDSM states fetched for {len(states)}/{len(system_names)} systems")
    except Exception as e:
        print(f"\n[BGS] EDSM lookup failed ({type(e).__name__}: {e}) - BGS column will not be updated")


def start_background_fetch(system_names, path=OUTPUT_FILE):
    """Start the lookup in a background thread; returns the thread."""
    thread = threading.Thread(target=_worker, args=(list(system_names), path), name='edsm-bgs')
    thread.start()
    return thread


def load_bgs_states(path=OUTPUT_FILE):
    """Read the last lookup, or {} if it's missing, unreadable, or older than MAX_AGE."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        age = datetime.now(timezone.utc) - datetime.fromisoformat(data['fetched_at'])
        return (data.get('states') or {}) if age <= MAX_AGE else {}
    except (OSError, ValueError, KeyError, TypeError):
        return {}
