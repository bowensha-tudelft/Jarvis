"""HTTP, keys and the on-disk cache. Standard library only.

Keys come from environment variables first, then ~/.jarvis/config.json. They are never
put into URLs (every source accepts a header), so a cache key never contains a secret and
an error message that echoes a URL never leaks one.
"""
import gzip
import hashlib
import random
import json
import os
import time
import urllib.error
import urllib.request

HOME = os.path.join(os.path.expanduser('~'), '.jarvis')
CONFIG_PATH = os.path.join(HOME, 'config.json')
CACHE_DIR = os.path.join(HOME, 'cache')
UA = 'jarvis-research/0.1 (Claude Code skill)'

KEY_NAMES = {
    'openalex': ('OPENALEX_API_KEY', 'openalex_api_key'),
    's2': ('S2_API_KEY', 's2_api_key'),
    'tavily': ('TAVILY_API_KEY', 'tavily_api_key'),
    'firecrawl': ('FIRECRAWL_API_KEY', 'firecrawl_api_key'),
}

_config = None
FRESH = False          # set by --fresh: skip cache reads (writes still happen)


class SourceError(Exception):
    """A request to one source failed. `status` is the HTTP code, 0 for network errors."""

    def __init__(self, source, status, message):
        super().__init__('%s: %s' % (source, message))
        self.source = source
        self.status = status


def _load_config():
    global _config
    if _config is None:
        try:
            with open(CONFIG_PATH, encoding='utf-8-sig') as f:
                _config = json.load(f)
        except FileNotFoundError:
            _config = {}
        except (OSError, ValueError) as e:
            raise SystemExit('Cannot read %s: %s' % (CONFIG_PATH, e))
    return _config


def key(source):
    env, field = KEY_NAMES[source]
    return (os.environ.get(env) or _load_config().get(field) or '').strip()


def _cache_path(sig):
    return os.path.join(CACHE_DIR, sig[:2], sig + '.json')


def _cache_get(sig, ttl):
    if FRESH or ttl <= 0:
        return None
    p = _cache_path(sig)
    try:
        if time.time() - os.path.getmtime(p) > ttl:
            return None
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _cache_put(sig, value):
    p = _cache_path(sig)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        pass        # a cache that cannot be written must never stop a search


def request(source, url, *, method='GET', body=None, headers=None, ttl=0,
            timeout=60, retries=0, raw=False):
    """Return parsed JSON (or text when raw=True). Raises SourceError.

    `retries` applies to 429 and 5xx only, with 2/4/8 s back-off. OpenAlex passes 0:
    its 429 means the daily budget is gone, and retrying only burns more of it.
    """
    data = json.dumps(body).encode('utf-8') if body is not None else None
    sig = hashlib.sha256(('%s %s %s %s' % (method, url, data and data.decode('utf-8'), raw)).encode('utf-8')).hexdigest()
    hit = _cache_get(sig, ttl)
    if hit is not None:
        return hit['v']

    h = {'User-Agent': UA, 'Accept': 'application/json'}
    if data is not None:
        h['Content-Type'] = 'application/json'
    h.update(headers or {})
    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body_bytes = resp.read()
            # OpenAlex's content API stores and serves gzip regardless of Accept-Encoding.
            if body_bytes[:2] == b'\x1f\x8b':
                body_bytes = gzip.decompress(body_bytes)
            text = body_bytes.decode('utf-8', 'replace')
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', 'replace')[:300]
            if (e.code == 429 or e.code >= 500) and attempt < retries:
                attempt += 1
                time.sleep(min(2 ** attempt, 8) * (0.5 + random.random()))   # jitter: S2's 429s come in bursts
                continue
            raise SourceError(source, e.code, 'HTTP %d %s' % (e.code, _short(detail)))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < retries:
                attempt += 1
                time.sleep(2 ** attempt)
                continue
            raise SourceError(source, 0, 'network error: %s' % getattr(e, 'reason', e))

    if raw:
        value = text
    else:
        try:
            value = json.loads(text)
        except ValueError:
            raise SourceError(source, 200, 'not JSON: %s' % _short(text))
    if ttl > 0:
        _cache_put(sig, {'v': value})
    return value


def _short(s):
    s = ' '.join(str(s).split())
    return s[:200] + ('...' if len(s) > 200 else '')


def cache_size():
    n = size = 0
    for root, _, files in os.walk(CACHE_DIR):
        for f in files:
            n += 1
            try:
                size += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n, size
