#!/usr/bin/env python3
"""
FLAGS BATTLE - circular flag balls bounce in a ring, damage each other, and
get eliminated until one country is left. Loops forever (24/7 stream ready).

Vertical 720x1280. Flag images are downloaded once from flagcdn.com into ./flags/
(if a download fails, that country gets a coloured placeholder with its code).

Run:       python flags_battle.py            (Windows)
VPS:       DISPLAY=:100 python3 flags_battle.py
Quick test: SDL_VIDEODRIVER=dummy MAX_ROUNDS=1 python3 flags_battle.py
"""
import array
import glob
import json
import math
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pygame

# ---------------------------------------------------------------- config ----
W, H = 720, 1280
FPS = 30
SUBSTEPS = 2                  # physics steps per frame (dt = 1/(FPS*SUBSTEPS))
FLAGS_PER_ROUND = 32          # how many countries fight each round
HP_MIN, HP_MAX = 40, 110      # each flag gets random HP so fights vary
DAMAGE_MIN, DAMAGE_MAX = 0.8, 1.6
HIT_COOLDOWN = 0.20           # seconds a flag is immune after being hit
SPEED_MIN, SPEED_MAX = 200, 340
SHRINK_START = 35.0           # seconds before the arena starts shrinking
SHRINK_DURATION = 45.0        # seconds to shrink down to SHRINK_TO
SHRINK_TO = 0.38              # final radius as fraction of the start radius
WINNER_SECS = 6.0
TITLE = "FLAGS BATTLE"
SUBTITLE = "Last flag standing wins"   # put your channel text here

# ---- YouTube chat ----
# Viewers type a country name (or post a flag emoji) in live chat -> that flag joins
# the NEXT round. Remaining slots are filled randomly. No chat = fully random.
CHAT_POLL_SECS = 60           # API quota: 5 units/poll, 10,000 units/day => keep >= 45
COLLECT_SECS = 12             # "type your country!" window shown after each winner
MAX_PER_VIEWER = 3            # max countries one viewer can add per batch
BOOST_HP = 15                 # HP healed by one "!boost <country>"
MAX_BOOSTS_PER_BATCH = 15     # boosts accepted per chat poll (1 per viewer per poll)
BOOST_SPACING = 0.35          # seconds between boosts so they show one by one
CHAT_CONFIG_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_config.json"),
    os.path.expanduser("~/falling-pickaxe/config.json"),   # reuses your pickaxe API key + livestream ID
]

# ---- Audio ----
MUSIC_VOLUME = 0.05           # background music: 5%  (0.0 - 1.0)
SFX_VOLUME = 0.35             # sound effects volume
SFX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sfx")       # optional: your own hit1.wav, hit2.mp3 ... replace the built-in fight sounds
MUSIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music")   # put lofi .mp3/.ogg/.wav here

ARENA_CENTER = (W // 2, 575)
ARENA_R = 322

BASE = os.path.dirname(os.path.abspath(__file__))
FLAG_DIR = os.path.join(BASE, "flags")
WINS_FILE = os.path.join(BASE, "wins.json")
MAX_ROUNDS = int(os.environ.get("MAX_ROUNDS", "0"))   # 0 = infinite

# code (flagcdn, lowercase) -> display name. Edit freely.
COUNTRIES = {
    "in": "India", "us": "USA", "gb": "UK", "cn": "China", "jp": "Japan",
    "ru": "Russia", "br": "Brazil", "de": "Germany", "fr": "France", "it": "Italy",
    "es": "Spain", "ca": "Canada", "au": "Australia", "mx": "Mexico",
    "kr": "South Korea", "id": "Indonesia", "tr": "Turkey", "sa": "Saudi Arabia",
    "za": "South Africa", "eg": "Egypt", "ng": "Nigeria", "ar": "Argentina",
    "pk": "Pakistan", "bd": "Bangladesh", "lk": "Sri Lanka", "np": "Nepal",
    "af": "Afghanistan", "ir": "Iran", "iq": "Iraq", "ae": "UAE", "il": "Israel",
    "ua": "Ukraine", "pl": "Poland", "nl": "Netherlands", "be": "Belgium",
    "ch": "Switzerland", "se": "Sweden", "no": "Norway", "dk": "Denmark",
    "fi": "Finland", "pt": "Portugal", "gr": "Greece", "at": "Austria",
    "ie": "Ireland", "cz": "Czechia", "hu": "Hungary", "ro": "Romania",
    "th": "Thailand", "vn": "Vietnam", "my": "Malaysia", "sg": "Singapore",
    "ph": "Philippines", "nz": "New Zealand", "cl": "Chile", "co": "Colombia",
    "pe": "Peru", "ve": "Venezuela", "cu": "Cuba", "ke": "Kenya",
    "et": "Ethiopia", "ma": "Morocco", "dz": "Algeria", "gh": "Ghana",
    "qa": "Qatar", "kz": "Kazakhstan",
    "tw": "Taiwan", "by": "Belarus", "rs": "Serbia", "hr": "Croatia", "bg": "Bulgaria",
    "sk": "Slovakia", "si": "Slovenia", "lt": "Lithuania", "lv": "Latvia", "ee": "Estonia",
    "is": "Iceland", "lu": "Luxembourg", "mt": "Malta", "cy": "Cyprus", "ge": "Georgia",
    "am": "Armenia", "az": "Azerbaijan", "uz": "Uzbekistan", "mn": "Mongolia",
    "mm": "Myanmar", "kh": "Cambodia", "la": "Laos", "bt": "Bhutan", "mv": "Maldives",
    "jo": "Jordan", "lb": "Lebanon", "sy": "Syria", "ye": "Yemen", "om": "Oman",
    "kw": "Kuwait", "bh": "Bahrain", "tn": "Tunisia", "ly": "Libya", "sd": "Sudan",
    "tz": "Tanzania", "ug": "Uganda", "zw": "Zimbabwe", "zm": "Zambia", "ao": "Angola",
    "sn": "Senegal", "ci": "Ivory Coast", "cm": "Cameroon", "ec": "Ecuador",
    "bo": "Bolivia", "py": "Paraguay", "uy": "Uruguay", "cr": "Costa Rica",
    "pa": "Panama", "do": "Dominican Rep.", "jm": "Jamaica", "gt": "Guatemala",
}

# extra things viewers might type -> code
ALIASES = {
    "us": ["usa", "united states", "america", "united states of america"],
    "gb": ["uk", "united kingdom", "england", "britain", "great britain", "scotland"],
    "ae": ["uae", "emirates", "united arab emirates", "dubai"],
    "kr": ["korea"],
    "cz": ["czech republic", "czech"],
    "nl": ["holland"],
    "sa": ["saudi"],
    "tr": ["turkey", "turkiye", "t\u00fcrkiye"],
    "in": ["bharat", "hindustan"],
    "ci": ["cote d ivoire"],
    "do": ["dominican republic", "dominican"],
    "lk": ["srilanka"],
    "nz": ["newzealand"],
    "za": ["southafrica"],
}

BG_TOP, BG_BOT = (12, 16, 40), (40, 18, 58)


# ---------------------------------------------------------------- assets ----
def download_flags(progress=None):
    os.makedirs(FLAG_DIR, exist_ok=True)
    missing = [c for c in COUNTRIES if not os.path.exists(os.path.join(FLAG_DIR, c + ".png"))]
    for n, code in enumerate(missing):
        url = f"https://flagcdn.com/w160/{code}.png"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read()
            with open(os.path.join(FLAG_DIR, code + ".png"), "wb") as f:
                f.write(data)
        except Exception as ex:
            print(f"flag download failed for {code}: {ex}", file=sys.stderr)
        if progress:
            progress(n + 1, len(missing))


def placeholder(code, size=160):
    rnd = random.Random(code)
    col = (rnd.randint(40, 220), rnd.randint(40, 220), rnd.randint(40, 220))
    s = pygame.Surface((int(size * 1.5), size))
    s.fill(col)
    f = pygame.font.Font(None, int(size * 0.7))
    t = f.render(code.upper(), True, (255, 255, 255))
    s.blit(t, t.get_rect(center=s.get_rect().center))
    return s


def load_base_flags():
    flags = {}
    for code in COUNTRIES:
        path = os.path.join(FLAG_DIR, code + ".png")
        try:
            flags[code] = pygame.image.load(path).convert_alpha()
        except Exception:
            flags[code] = placeholder(code)
    return flags


def circle_crop(img, r):
    d = int(r * 2)
    iw, ih = img.get_size()
    scale = d / ih
    w = max(d, int(iw * scale))
    big = pygame.transform.smoothscale(img, (w, d))
    out = pygame.Surface((d, d), pygame.SRCALPHA)
    out.blit(big, (0, 0), pygame.Rect((w - d) // 2, 0, d, d))
    mask = pygame.Surface((d, d), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), (d // 2, d // 2), d // 2)
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    pygame.draw.circle(out, (255, 255, 255), (d // 2, d // 2), d // 2, 3)
    return out


def load_wins():
    try:
        with open(WINS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_wins(w):
    try:
        with open(WINS_FILE, "w") as f:
            json.dump(w, f)
    except Exception:
        pass



# ------------------------------------------------------------- YouTube chat --
def _norm_key(k):
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def _flatten(d, out=None):
    out = {} if out is None else out
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                _flatten(v, out)
            else:
                out.setdefault(_norm_key(k), v)
    elif isinstance(d, list):
        for v in d:
            _flatten(v, out)
    return out


def _video_id(v):
    v = str(v).strip()
    m = re.search(r"(?:live/|v=|youtu\.be/)([\w-]{6,})", v)
    return m.group(1) if m else v


def read_chat_cfg(paths=None):
    """chat_config.json may set everything; other files (your pickaxe config.json)
    are only used to find the API key + livestream ID. Re-read on every poll because
    the livestream ID changes with each new broadcast."""
    paths = paths or CHAT_CONFIG_PATHS
    cfg = {"enabled": True, "poll_secs": CHAT_POLL_SECS, "api_key": "",
           "livestream_id": "", "api_base": "https://www.googleapis.com"}
    for n, path in enumerate(paths):
        try:
            with open(path, encoding="utf-8") as f:
                flat = _flatten(json.load(f))
        except Exception:
            continue
        if n == 0:
            if "enabled" in flat:
                cfg["enabled"] = bool(flat["enabled"])
            if flat.get("pollsecs"):
                cfg["poll_secs"] = float(flat["pollsecs"])
            if flat.get("apibase"):
                cfg["api_base"] = str(flat["apibase"]).rstrip("/")
        if not cfg["api_key"]:
            for k, v in flat.items():
                if "apikey" in k and isinstance(v, str) and v.strip():
                    cfg["api_key"] = v.strip()
                    break
        if not cfg["livestream_id"]:
            for k, v in flat.items():
                if k in ("livestreamid", "videoid", "broadcastid", "liveid") and str(v).strip():
                    cfg["livestream_id"] = _video_id(v)
                    break
    return cfg


def _build_matcher():
    alias = {}
    for code, name in COUNTRIES.items():
        alias[re.sub(r"[^a-z\u00c0-\u024f ]", " ", name.lower()).strip()] = code
    for code, extras in ALIASES.items():
        for e in extras:
            alias[e] = code
    pats = sorted(alias, key=len, reverse=True)
    rx = re.compile(r"(?<![a-z\u00c0-\u024f])(" + "|".join(re.escape(p) for p in pats) +
                    r")(?![a-z\u00c0-\u024f])")
    return alias, rx


_ALIAS, _RX = _build_matcher()
_FLAG_RX = re.compile("[\U0001F1E6-\U0001F1FF]{2}")


def match_countries(text):
    """Return country codes mentioned in a chat message (order kept, no repeats)."""
    found = []
    for m in _FLAG_RX.finditer(text):
        code = "".join(chr(ord(ch) - 0x1F1E6 + 97) for ch in m.group())
        if code in COUNTRIES and code not in found:
            found.append(code)
    t = re.sub(r"[^a-z\u00c0-\u024f ]", " ", text.lower())
    t = re.sub(r"\s+", " ", t)
    for m in _RX.finditer(t):
        code = _ALIAS[m.group(1)]
        if code not in found:
            found.append(code)
    return found


class ChatCollector(threading.Thread):
    """Background thread: polls YouTube live chat, queues requested countries."""

    def __init__(self, cfg_paths=None):
        super().__init__(daemon=True)
        self.cfg_paths = cfg_paths
        self.lock = threading.Lock()
        self.pending = {}        # code -> {"votes", "by", "order"}
        self.seen = set()        # (author, code) pairs in the current batch
        self.per_user = {}       # author -> how many added this batch
        self.order = 0
        self.boosts = []         # (code, viewer) waiting to be applied
        self.boost_users = set()
        self.vid = None
        self.chat_id = None
        self.page_token = None
        self.backoff_until = 0.0
        self.last_ok = 0.0
        self.poll_wait = CHAT_POLL_SECS
        self.status = "starting"

    @property
    def active(self):
        return time.time() - self.last_ok < max(self.poll_wait * 3, 90)

    def request(self, code, by):
        """Queue a country for the next round (no per-viewer limits)."""
        with self.lock:
            if code in self.pending or len(self.pending) >= 300:
                return
            self.order += 1
            self.pending[code] = {"votes": 1, "by": by, "order": self.order}

    def take_boosts(self):
        with self.lock:
            out, self.boosts = self.boosts, []
            self.boost_users.clear()
            return out

    def add_message(self, author, name, text):
        m = re.match(r"\s*!boost\b(.*)", text, re.I | re.S)
        if m:                                    # "!boost <country>" heals that flag
            codes = match_countries(m.group(1))
            if codes:
                with self.lock:
                    if author not in self.boost_users and len(self.boosts) < MAX_BOOSTS_PER_BATCH:
                        self.boost_users.add(author)
                        self.boosts.append((codes[0], name))
            return
        codes = match_countries(text)
        with self.lock:
            for code in codes:
                if (author, code) in self.seen:
                    continue
                if self.per_user.get(author, 0) >= MAX_PER_VIEWER:
                    break
                self.seen.add((author, code))
                self.per_user[author] = self.per_user.get(author, 0) + 1
                e = self.pending.get(code)
                if e is None:
                    if len(self.pending) >= 300:
                        continue
                    self.order += 1
                    e = self.pending[code] = {"votes": 0, "by": name, "order": self.order}
                e["votes"] += 1

    def take(self, n):
        """Pop up to n requested countries (most voted first). Leftovers stay queued."""
        with self.lock:
            items = sorted(self.pending.items(), key=lambda kv: (-kv[1]["votes"], kv[1]["order"]))[:n]
            taken = {c for c, _ in items}
            for c in taken:
                del self.pending[c]
            self.seen = {k for k in self.seen if k[1] not in taken}
            if not self.pending:
                self.per_user.clear()
            return [(c, e["by"]) for c, e in items]

    def queue_preview(self, k=10):
        with self.lock:
            items = sorted(self.pending.items(), key=lambda kv: (-kv[1]["votes"], kv[1]["order"]))
            return [(COUNTRIES[c], e["by"]) for c, e in items[:k]], len(items)

    # ---- network ----
    def _get(self, cfg, path, params):
        params = dict(params, key=cfg["api_key"])
        url = f"{cfg['api_base']}/youtube/v3/{path}?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))

    def poll(self, cfg):
        if cfg["livestream_id"] != self.vid or not self.chat_id:
            data = self._get(cfg, "videos", {"part": "liveStreamingDetails", "id": cfg["livestream_id"]})
            items = data.get("items") or []
            chat_id = (items[0].get("liveStreamingDetails", {}).get("activeLiveChatId") if items else None)
            if not chat_id:
                self.status = "no active live chat for this livestream ID"
                self.vid, self.chat_id = cfg["livestream_id"], None
                return
            self.vid, self.chat_id, self.page_token = cfg["livestream_id"], chat_id, None
        for _ in range(3):                    # drain extra pages if chat is very busy
            params = {"liveChatId": self.chat_id, "part": "snippet,authorDetails", "maxResults": 2000}
            if self.page_token:
                params["pageToken"] = self.page_token
            data = self._get(cfg, "liveChat/messages", params)
            self.page_token = data.get("nextPageToken", self.page_token)
            items = data.get("items", [])
            for it in items:
                sn = it.get("snippet", {})
                au = it.get("authorDetails", {})
                text = sn.get("displayMessage") or sn.get("textMessageDetails", {}).get("messageText", "")
                if text:
                    self.add_message(au.get("channelId", au.get("displayName", "?")),
                                     au.get("displayName", "viewer"), text)
            if len(items) < 2000:
                break
        self.last_ok = time.time()
        self.status = "connected"

    def run(self):
        while True:
            cfg = read_chat_cfg(self.cfg_paths)
            self.poll_wait = max(20.0, float(cfg["poll_secs"]))
            try:
                if not cfg["enabled"]:
                    self.status = "disabled"
                elif not cfg["api_key"] or not cfg["livestream_id"]:
                    self.status = "no API key / livestream ID found"
                elif time.time() < self.backoff_until:
                    self.status = "quota backoff"
                else:
                    self.poll(cfg)
            except urllib.error.HTTPError as ex:
                reason = ""
                try:
                    reason = json.loads(ex.read().decode("utf-8"))["error"]["errors"][0]["reason"]
                except Exception:
                    pass
                self.status = f"http {ex.code} {reason}"
                print("chat:", self.status, file=sys.stderr)
                if reason in ("quotaExceeded", "dailyLimitExceeded"):
                    self.backoff_until = time.time() + 3600
                elif reason in ("rateLimitExceeded", "userRateLimitExceeded"):
                    self.backoff_until = time.time() + 300
                else:                         # chat ended / bad id -> look the chat up again
                    self.chat_id = None
            except Exception as ex:
                self.status = f"error {ex!r}"
                print("chat:", self.status, file=sys.stderr)
            time.sleep(self.poll_wait)



# ------------------------------------------------------------------ audio ----
class Audio:
    """Procedural sound effects (no asset files) + looping shuffled background music."""
    RATE = 44100

    def __init__(self):
        self.enabled = False
        self.tracks, self.cur = [], -1
        self.last_hit = 0.0
        self.retry_at = 0.0
        try:
            pygame.mixer.init(frequency=self.RATE, size=-16, channels=2, buffer=1024)
            pygame.mixer.set_num_channels(24)
            self.enabled = True
        except Exception as ex:
            print("audio disabled (no sound device):", ex, file=sys.stderr)
            return
        custom = self._load_custom_hits()
        self.custom = bool(custom)
        self.hits = custom or ([self._sound(self._punch(f)) for f in (150, 185)] + [self._sound(self._slap())])
        self.heavy = self._sound(self._heavy())
        self.kill = self._sound(self._kill())
        self.win = self._sound(self._win())
        self.chime = self._sound(self._chime())
        self.tick = self._sound(self._tone(1000, 0.04, 60))
        self.boost = self._sound(self._boost())
        pygame.mixer.music.set_volume(MUSIC_VOLUME)
        files = []
        for ext in ("mp3", "ogg", "wav"):
            files += glob.glob(os.path.join(MUSIC_DIR, "*." + ext))
        random.shuffle(files)
        self.tracks = files
        if not files:
            print(f"no background music found - put lofi .mp3/.ogg/.wav files in: {MUSIC_DIR}", file=sys.stderr)

    # -- synthesis (floats in -1..1) --
    def _tone(self, f, dur, decay):
        n = int(self.RATE * dur)
        return [math.sin(math.tau * f * i / self.RATE) * math.exp(-decay * i / self.RATE) for i in range(n)]

    def _punch(self, f0):
        """Thump (pitch drop) + crack + short noise burst = a punch landing."""
        n = int(self.RATE * 0.18)
        out, ph = [], 0.0
        for i in range(n):
            t = i / self.RATE
            ph += math.tau * (f0 * 0.38 + f0 * math.exp(-t * 38)) / self.RATE
            v = math.sin(ph) * math.exp(-t * 26) * 0.95
            v += math.sin(math.tau * 950 * t) * math.exp(-t * 130) * 0.35
            v += random.uniform(-1, 1) * math.exp(-t * 210) * 0.55
            out.append(v)
        return out

    def _slap(self):
        """Bright noisy smack."""
        n = int(self.RATE * 0.14)
        out, prev = [], 0.0
        for i in range(n):
            t = i / self.RATE
            noise = random.uniform(-1, 1)
            hp = noise - prev                      # crude high-pass = sharper "slap"
            prev = noise
            v = hp * math.exp(-t * 55) * 0.7 + math.sin(math.tau * 420 * t) * math.exp(-t * 60) * 0.45
            out.append(v)
        return out

    def _heavy(self):
        """Big knock-out style smash for hard collisions."""
        n = int(self.RATE * 0.32)
        out, ph = [], 0.0
        for i in range(n):
            t = i / self.RATE
            ph += math.tau * (42 + 110 * math.exp(-t * 22)) / self.RATE
            v = math.sin(ph) * math.exp(-t * 14) * 1.0
            v += random.uniform(-1, 1) * math.exp(-t * 90) * 0.6
            v += math.sin(math.tau * 600 * t) * math.exp(-t * 90) * 0.3
            out.append(v)
        return out

    def _load_custom_hits(self):
        """Optional: put your own fight sounds in the 'sfx' folder named hit*.wav/.ogg/.mp3"""
        found = []
        for ext in ("wav", "ogg", "mp3"):
            found += glob.glob(os.path.join(SFX_DIR, "hit*." + ext))
        sounds = []
        for p in sorted(found):
            try:
                snd = pygame.mixer.Sound(p)
                snd.set_volume(SFX_VOLUME)
                sounds.append(snd)
            except Exception as ex:
                print("bad sfx file", p, ex, file=sys.stderr)
        return sounds

    def _kill(self):
        n = int(self.RATE * 0.32)
        out, ph = [], 0.0
        for i in range(n):
            t = i / self.RATE
            ph += math.tau * (90 + 650 * math.exp(-t * 9)) / self.RATE
            v = math.sin(ph) * math.exp(-t * 7)
            if t < 0.03:
                v += random.uniform(-1, 1) * 0.6 * (1 - t / 0.03)
            out.append(v * 0.9)
        return out

    def _win(self):
        out = []
        for f, d in ((523.25, 0.16), (659.25, 0.16), (783.99, 0.16), (1046.5, 0.7)):
            n = int(self.RATE * d)
            for i in range(n):
                t = i / self.RATE
                env = min(1.0, t / 0.01) * math.exp(-t * (3 if d > 0.5 else 9))
                out.append((math.sin(math.tau * f * t) * 0.6 + math.sin(math.tau * f * 2 * t) * 0.2) * env)
        return out

    def _chime(self):
        out = []
        for f, d in ((880, 0.12), (1320, 0.3)):
            n = int(self.RATE * d)
            out += [math.sin(math.tau * f * i / self.RATE) * math.exp(-8 * i / self.RATE) * 0.7 for i in range(n)]
        return out

    def _boost(self):
        out = []
        for f, d in ((660, 0.07), (990, 0.18)):
            n = int(self.RATE * d)
            out += [math.sin(math.tau * f * i / self.RATE) * math.exp(-9 * i / self.RATE) * 0.7 for i in range(n)]
        return out

    def _sound(self, samples):
        a = array.array("h")
        for v in samples:
            x = int(max(-1.0, min(1.0, v)) * 30000)
            a.append(x)
            a.append(x)
        snd = pygame.mixer.Sound(buffer=a.tobytes())
        snd.set_volume(SFX_VOLUME)
        return snd

    # -- events --
    def on_hit(self, power=0.5):
        """power = collision speed 0..1 (harder hit = louder, and big ones use the heavy smash)."""
        now = time.time()
        p = max(0.0, min(1.0, power))
        gap = 0.05 if p > 0.72 else 0.09            # hard hits get through more often
        if not self.enabled or p < 0.15 or now - self.last_hit < gap:   # thin out pile-ups
            return
        self.last_hit = now
        snd = self.heavy if (p > 0.72 and not self.custom) else random.choice(self.hits)
        ch = snd.play()
        if ch:
            ch.set_volume(0.35 + 0.65 * p)

    def on_kill(self):
        if self.enabled:
            self.kill.play()

    def on_win(self):
        if self.enabled:
            self.win.play()

    def on_chat_flags(self):
        if self.enabled:
            self.chime.play()

    def on_boost(self):
        if self.enabled:
            self.boost.play()

    def on_tick(self):
        if self.enabled:
            self.tick.play()

    def update(self):
        """Call every frame: keeps the music playlist going forever."""
        if not self.enabled or not self.tracks or pygame.mixer.music.get_busy():
            return
        if time.time() < self.retry_at:
            return
        for _ in range(len(self.tracks)):
            self.cur = (self.cur + 1) % len(self.tracks)
            try:
                pygame.mixer.music.load(self.tracks[self.cur])
                pygame.mixer.music.set_volume(MUSIC_VOLUME)
                pygame.mixer.music.play()
                return
            except Exception as ex:
                print("bad music file", self.tracks[self.cur], ex, file=sys.stderr)
        self.retry_at = time.time() + 10


# ----------------------------------------------------------------- model ----
class Ball:
    def __init__(self, code, r, surf, icon):
        self.code, self.name = code, COUNTRIES[code]
        self.r = r
        self.surf, self.icon = surf, icon
        self.pos = pygame.Vector2()
        self.vel = pygame.Vector2()
        self.maxhp = random.uniform(HP_MIN, HP_MAX)
        self.hp = self.maxhp
        self.last_hit = -9.0
        self.flash = 0.0
        self.hit_by = None
        self.by = None          # chat viewer who requested this flag
        self.boost_flash = 0.0


class Round:
    def __init__(self, base_flags, forced=()):
        forced = [(c, by) for c, by in forced if c in COUNTRIES][:FLAGS_PER_ROUND]
        by_code = dict(forced)
        pool = [c for c in COUNTRIES if c not in by_code]
        codes = [c for c, _ in forced] + random.sample(pool, FLAGS_PER_ROUND - len(forced))
        random.shuffle(codes)
        n = len(codes)
        self.r_ball = max(18, min(34, int(ARENA_R * 0.9 / math.sqrt(n) / 1.35)))
        self.balls = []
        for c in codes:
            surf = circle_crop(base_flags[c], self.r_ball)
            icon = pygame.transform.smoothscale(circle_crop(base_flags[c], 40), (32, 32))
            ball = Ball(c, self.r_ball, surf, icon)
            ball.by = by_code.get(c)
            self.balls.append(ball)
        self.t = 0.0
        self.R = float(ARENA_R)
        self.eliminated = []      # newest last: (name, by_name)
        self.particles = []       # [x, y, vx, vy, life, colour]
        self.winner = None
        self.events = []          # 'hit' / 'kill' for the sound system
        self.feed = []            # (text, colour) messages for the bottom ticker
        self.floaters = []        # [x, y, text, life] floating +HP numbers
        self._spawn()

    def _spawn(self):
        placed = []
        for b in self.balls:
            for _ in range(500):
                ang = random.uniform(0, math.tau)
                dist = random.uniform(0, ARENA_R - b.r - 6)
                p = pygame.Vector2(math.cos(ang), math.sin(ang)) * dist
                if all((p - q.pos).length() > b.r + q.r + 4 for q in placed):
                    break
            b.pos = p
            a = random.uniform(0, math.tau)
            b.vel = pygame.Vector2(math.cos(a), math.sin(a)) * random.uniform(SPEED_MIN, SPEED_MAX)
            placed.append(b)

    @property
    def alive(self):
        return [b for b in self.balls if b.hp > 0]

    def step(self, dt):
        self.t += dt
        if self.t > SHRINK_START:
            k = min(1.0, (self.t - SHRINK_START) / SHRINK_DURATION)
            self.R = ARENA_R * (1 - k * (1 - SHRINK_TO))
        alive = self.alive
        for b in alive:
            b.pos += b.vel * dt
            b.flash = max(0.0, b.flash - dt)
            b.boost_flash = max(0.0, b.boost_flash - dt)
            d = b.pos.length()
            if d > self.R - b.r:
                n = b.pos / d if d else pygame.Vector2(1, 0)
                b.pos = n * (self.R - b.r)
                vn = b.vel.dot(n)
                if vn > 0:
                    b.vel -= 2 * vn * n
        died_now = []
        for i in range(len(alive)):
            a = alive[i]
            for j in range(i + 1, len(alive)):
                c = alive[j]
                delta = c.pos - a.pos
                dist = delta.length()
                rr = a.r + c.r
                if dist >= rr or dist == 0:
                    continue
                n = delta / dist
                over = rr - dist
                a.pos -= n * over / 2
                c.pos += n * over / 2
                rel = (a.vel - c.vel).dot(n)
                if rel > 0:                        # approaching -> bounce + damage
                    a.vel -= rel * n
                    c.vel += rel * n
                    hit_any = False
                    for x, y in ((a, c), (c, a)):
                        if self.t - x.last_hit > HIT_COOLDOWN and x.hp > 0:
                            x.hp -= random.uniform(DAMAGE_MIN, DAMAGE_MAX)
                            x.last_hit = self.t
                            x.flash = 0.12
                            x.hit_by = y
                            hit_any = True
                            if x.hp <= 0 and x not in died_now:
                                died_now.append(x)
                    if hit_any:
                        self.events.append(("hit", rel))
        for b in alive:                            # keep the action lively
            s = b.vel.length()
            if s < 1e-3:
                b.vel = pygame.Vector2(1, 0) * SPEED_MIN
            elif s < SPEED_MIN:
                b.vel *= SPEED_MIN / s
            elif s > SPEED_MAX:
                b.vel *= SPEED_MAX / s
        for b in died_now:
            by = b.hit_by.name if b.hit_by else "the wall"
            self.eliminated.append((b.name, by))
            self.feed.append((f"{b.name} eliminated by {by}", (255, 140, 140)))
            self.events.append(("kill", 0))
            for _ in range(16):
                a = random.uniform(0, math.tau)
                sp = random.uniform(60, 240)
                self.particles.append([b.pos.x, b.pos.y, math.cos(a) * sp, math.sin(a) * sp, 0.6,
                                       random.choice([(255, 214, 102), (255, 255, 255), (231, 76, 60)])])
        for p in self.particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[4] -= dt
        self.particles = [p for p in self.particles if p[4] > 0]
        for fl in self.floaters:
            fl[1] -= 45 * dt
            fl[3] -= dt
        self.floaters = [fl for fl in self.floaters if fl[3] > 0]
        left = self.alive
        if len(left) <= 1 and self.winner is None:
            if left:
                self.winner = left[0]
            elif died_now:
                self.winner = max(died_now, key=lambda x: x.hp)   # simultaneous KO
                self.winner.hp = max(self.winner.hp, 1)


    def boost(self, code, by):
        """Heal a living flag. Returns True if a flag was boosted."""
        for b in self.balls:
            if b.code == code and b.hp > 0:
                gained = min(BOOST_HP, b.maxhp - b.hp)
                b.hp = min(b.maxhp, b.hp + BOOST_HP)
                b.boost_flash = 0.5
                self.floaters.append([b.pos.x, b.pos.y - b.r, f"+{max(1, int(round(gained)))}", 1.0])
                self.feed.append((f"{by} boosted {b.name}!", (110, 235, 140)))
                self.events.append(("boost", 0))
                return True
        return False


# --------------------------------------------------------------- display ----
class App:
    def __init__(self):
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_caption(TITLE)
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.f_title = self._font(78, True)
        self.f_big = self._font(64, True)
        self.f_mid = self._font(38, True)
        self.f_row = self._font(30, True)
        self.f_small = self._font(26, False)
        self.bg = self._make_bg()
        self.wins = load_wins()
        self.round_no = 0
        self.base_flags = {}
        self.chat = ChatCollector()
        self.audio = Audio()

    @staticmethod
    def _font(size, bold):
        for name in ("dejavusans", "arial", "freesans"):
            try:
                return pygame.font.SysFont(name, size, bold=bold)
            except Exception:
                pass
        return pygame.font.Font(None, size)

    def _make_bg(self):
        s = pygame.Surface((W, H))
        for y in range(H):
            t = y / H
            pygame.draw.line(s, tuple(int(BG_TOP[k] * (1 - t) + BG_BOT[k] * t) for k in range(3)), (0, y), (W, y))
        return s

    def pump(self):
        self.audio.update()
        for e in pygame.event.get():
            if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                pygame.quit()
                sys.exit(0)

    def text(self, font, s, color, center):
        t = font.render(s, True, color)
        self.screen.blit(t, t.get_rect(center=center))

    def loading(self, done, total):
        self.pump()
        self.screen.blit(self.bg, (0, 0))
        self.text(self.f_title, TITLE, (255, 255, 255), (W // 2, 300))
        self.text(self.f_mid, f"Downloading flags {done}/{total}", (190, 200, 230), (W // 2, 480))
        pygame.display.flip()

    def draw(self, rd):
        scr = self.screen
        scr.blit(self.bg, (0, 0))
        # header
        pygame.draw.rect(scr, (220, 40, 40), (24, 30, 92, 40), border_radius=10)
        self.text(self.f_row, "LIVE", (255, 255, 255), (70, 50))
        self.text(self.f_title, TITLE, (255, 255, 255), (W // 2, 105))
        sub = SUBTITLE
        if self.chat.active:
            sub = (SUBTITLE, "Type a country in chat to join the next round!",
                   "Type !boost <country> to heal a flag!")[int(time.time() // 5) % 3]
        self.text(self.f_small, sub, (190, 200, 230), (W // 2, 168))
        alive = rd.alive
        self.text(self.f_mid, f"ROUND {self.round_no}   |   ALIVE {len(alive)}/{len(rd.balls)}",
                  (255, 214, 102), (W // 2, 215))
        # arena
        cx, cy = ARENA_CENTER
        pygame.draw.circle(scr, (10, 12, 30), ARENA_CENTER, int(rd.R))
        shrinking = rd.t > SHRINK_START
        pygame.draw.circle(scr, (255, 90, 90) if shrinking else (120, 200, 255), ARENA_CENTER, int(rd.R), 8)
        for b in alive:
            x, y = cx + b.pos.x, cy + b.pos.y
            scr.blit(b.surf, b.surf.get_rect(center=(x, y)))
            if b.by:
                pygame.draw.circle(scr, (255, 214, 102), (int(x), int(y)), b.r, 4)
            if b.flash > 0:
                pygame.draw.circle(scr, (255, 70, 70), (int(x), int(y)), b.r, 5)
            if b.boost_flash > 0:
                pygame.draw.circle(scr, (90, 240, 130), (int(x), int(y)), b.r + 3, 6)
            w = b.r * 1.6
            frac = max(0.0, b.hp / b.maxhp)
            bar = pygame.Rect(0, 0, w, 6)
            bar.center = (x, y - b.r - 8)
            pygame.draw.rect(scr, (55, 58, 85), bar.inflate(2, 2), border_radius=3)
            col = (80, 220, 110) if frac > 0.5 else (240, 200, 60) if frac > 0.25 else (235, 70, 70)
            pygame.draw.rect(scr, col, (bar.x, bar.y, w * frac, 6), border_radius=3)
        for p in rd.particles:
            pygame.draw.circle(scr, p[5], (int(cx + p[0]), int(cy + p[1])), 4)
        for fx, fy, txt, life in rd.floaters:
            t = self.f_row.render(txt, True, (110, 245, 150))
            t.set_alpha(int(255 * min(1.0, life * 1.5)))
            scr.blit(t, t.get_rect(center=(cx + fx, cy + fy)))
        # leaderboard
        top = sorted(alive, key=lambda b: -b.hp)[:5]
        y0 = 925
        self.text(self.f_mid, "LEADERBOARD", (255, 255, 255), (W // 2, y0))
        for k, b in enumerate(top):
            y = y0 + 48 + k * 40
            self.text(self.f_row, f"{k + 1}", (255, 214, 102), (110, y))
            scr.blit(b.icon, b.icon.get_rect(center=(160, y)))
            t = self.f_row.render(b.name, True, (255, 255, 255))
            scr.blit(t, (190, y - t.get_height() // 2))
            frac = max(0.0, b.hp / b.maxhp)
            pygame.draw.rect(scr, (40, 44, 70), (470, y - 8, 140, 16), border_radius=8)
            pygame.draw.rect(scr, (80, 220, 110), (470, y - 8, 140 * frac, 16), border_radius=8)
        # chat queue + elimination ticker
        if self.chat.active:
            names, total = self.chat.queue_preview(4)
            line = ", ".join(n for n, _ in names) + (f" +{total - len(names)}" if total > len(names) else "")
            self.text(self.f_small, "NEXT: " + line if names else "NEXT: random flags - type yours in chat!",
                      (255, 214, 102), (W // 2, 1177))
        for k, (msg, col) in enumerate(rd.feed[-2:][::-1]):
            self.text(self.f_small, msg, col if k == 0 else (150, 150, 180), (W // 2, 1213 + k * 36))

    def draw_winner(self, rd):
        w = rd.winner
        box = pygame.Rect(0, 0, 560, 520)
        box.center = (W // 2, ARENA_CENTER[1])
        pygame.draw.rect(self.screen, (16, 18, 40), box, border_radius=36)
        pygame.draw.rect(self.screen, (255, 214, 102), box, 6, border_radius=36)
        self.text(self.f_big, "WINNER!", (255, 214, 102), (W // 2, box.top + 70))
        big = pygame.transform.smoothscale(w.surf, (200, 200))
        self.screen.blit(big, big.get_rect(center=(W // 2, box.top + 240)))
        self.text(self.f_big, w.name, (255, 255, 255), (W // 2, box.top + 400))
        n = self.wins.get(w.code, 0)
        sub = f"Total wins: {n}" + (f"   |   requested by {w.by}" if w.by else "")
        self.text(self.f_small, sub, (190, 200, 230), (W // 2, box.top + 470))

    def draw_collect(self, secs_left):
        scr = self.screen
        scr.blit(self.bg, (0, 0))
        self.text(self.f_title, TITLE, (255, 255, 255), (W // 2, 105))
        self.text(self.f_big, "TYPE YOUR COUNTRY", (255, 214, 102), (W // 2, 300))
        self.text(self.f_big, "IN THE CHAT!", (255, 214, 102), (W // 2, 372))
        self.text(self.f_small, "Your flag joins the next battle", (190, 200, 230), (W // 2, 440))
        names, total = self.chat.queue_preview(10)
        box = pygame.Rect(90, 490, W - 180, 560)
        pygame.draw.rect(scr, (16, 18, 40), box, border_radius=28)
        pygame.draw.rect(scr, (120, 200, 255), box, 4, border_radius=28)
        if names:
            for k, (n, by) in enumerate(names):
                self.text(self.f_row, f"{n}", (255, 255, 255), (W // 2 - 90, box.top + 45 + k * 50))
                t = self.f_small.render(f"@{by}"[:16], True, (150, 160, 200))
                scr.blit(t, (W // 2 + 60, box.top + 45 + k * 50 - t.get_height() // 2))
            if total > len(names):
                self.text(self.f_small, f"+{total - len(names)} more", (190, 200, 230), (W // 2, box.bottom - 28))
        else:
            self.text(self.f_row, "No requests yet", (190, 200, 230), (W // 2, box.centery - 20))
            self.text(self.f_small, "Random flags will fill the arena", (150, 160, 200), (W // 2, box.centery + 25))
        self.text(self.f_mid, f"Battle starts in {max(0, int(secs_left) + 1)}", (255, 255, 255), (W // 2, 1130))

    def collect_window(self):
        end = time.time() + COLLECT_SECS
        last_sec = None
        while time.time() < end:
            self.pump()
            sec = int(end - time.time())
            if sec != last_sec and sec < 4:        # countdown ticks for the last seconds
                self.audio.on_tick()
            last_sec = sec
            self.draw_collect(end - time.time())
            pygame.display.flip()
            self.clock.tick(FPS)

    def run_round(self):
        forced = self.chat.take(FLAGS_PER_ROUND)
        rd = Round(self.base_flags, forced)
        if forced:
            self.audio.on_chat_flags()
        self.round_no += 1
        dt = 1.0 / (FPS * SUBSTEPS)
        boost_q, last_boost = [], 0.0
        while rd.winner is None:
            self.pump()
            boost_q += self.chat.take_boosts()
            if boost_q and time.time() - last_boost >= BOOST_SPACING:
                code, by = boost_q.pop(0)
                last_boost = time.time()
                if not rd.boost(code, by):               # not fighting right now
                    self.chat.request(code, by)          # -> treat as "join next round"

            for _ in range(SUBSTEPS):
                rd.step(dt)
            for name, val in rd.events:
                if name == "hit":
                    self.audio.on_hit(val / (SPEED_MAX * 1.3))     # harder collision = louder hit
                elif name == "kill":
                    self.audio.on_kill()
                else:
                    self.audio.on_boost()
            rd.events.clear()
            self.draw(rd)
            pygame.display.flip()
            self.clock.tick(FPS)
        w = rd.winner
        self.audio.on_win()
        self.wins[w.code] = self.wins.get(w.code, 0) + 1
        save_wins(self.wins)
        end = time.time() + WINNER_SECS
        while time.time() < end:
            self.pump()
            self.draw(rd)
            self.draw_winner(rd)
            pygame.display.flip()
            self.clock.tick(FPS)
        if self.chat.active:                    # only wait for chat if chat is really connected
            self.collect_window()

    def run(self):
        download_flags(self.loading)
        self.base_flags = load_base_flags()
        self.chat.start()
        while True:
            self.run_round()
            if MAX_ROUNDS and self.round_no >= MAX_ROUNDS:
                return


def main():
    while True:
        try:
            App().run()
            if MAX_ROUNDS:
                return
        except SystemExit:
            raise
        except Exception as ex:    # never die on a 24/7 stream
            print("error, restarting:", repr(ex), file=sys.stderr)
            time.sleep(2)
            try:
                pygame.quit()
            except Exception:
                pass


if __name__ == "__main__":
    main()
