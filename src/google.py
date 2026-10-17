"""Google Shopping URLs: country domains, interface languages, location pinning (uule) and filter/sort tokens (shoprs)."""
from __future__ import annotations

import base64
from urllib.parse import parse_qs, urlencode, urlsplit

from .pb import b64e, enc

# code: (google domain, default hl, gl, canonical location name for uule)
COUNTRIES = {
    'us': ('google.com', 'en', 'us', 'United States'), 'gb': ('google.co.uk', 'en', 'uk', 'United Kingdom'),
    'ca': ('google.ca', 'en', 'ca', 'Canada'), 'au': ('google.com.au', 'en', 'au', 'Australia'),
    'nz': ('google.co.nz', 'en', 'nz', 'New Zealand'), 'ie': ('google.ie', 'en', 'ie', 'Ireland'),
    'in': ('google.co.in', 'en', 'in', 'India'), 'sg': ('google.com.sg', 'en', 'sg', 'Singapore'),
    'za': ('google.co.za', 'en', 'za', 'South Africa'), 'ph': ('google.com.ph', 'en', 'ph', 'Philippines'),
    'my': ('google.com.my', 'en', 'my', 'Malaysia'), 'ae': ('google.ae', 'en', 'ae', 'United Arab Emirates'),
    'de': ('google.de', 'de', 'de', 'Germany'), 'at': ('google.at', 'de', 'at', 'Austria'),
    'ch': ('google.ch', 'de', 'ch', 'Switzerland'), 'fr': ('google.fr', 'fr', 'fr', 'France'),
    'be': ('google.be', 'fr', 'be', 'Belgium'), 'es': ('google.es', 'es', 'es', 'Spain'),
    'it': ('google.it', 'it', 'it', 'Italy'), 'nl': ('google.nl', 'nl', 'nl', 'Netherlands'),
    'pt': ('google.pt', 'pt-PT', 'pt', 'Portugal'), 'pl': ('google.pl', 'pl', 'pl', 'Poland'),
    'se': ('google.se', 'sv', 'se', 'Sweden'), 'no': ('google.no', 'no', 'no', 'Norway'),
    'dk': ('google.dk', 'da', 'dk', 'Denmark'), 'fi': ('google.fi', 'fi', 'fi', 'Finland'),
    'cz': ('google.cz', 'cs', 'cz', 'Czechia'), 'gr': ('google.gr', 'el', 'gr', 'Greece'),
    'hu': ('google.hu', 'hu', 'hu', 'Hungary'), 'ro': ('google.ro', 'ro', 'ro', 'Romania'),
    'tr': ('google.com.tr', 'tr', 'tr', 'Turkey'), 'il': ('google.co.il', 'he', 'il', 'Israel'),
    'sa': ('google.com.sa', 'ar', 'sa', 'Saudi Arabia'), 'jp': ('google.co.jp', 'ja', 'jp', 'Japan'),
    'kr': ('google.co.kr', 'ko', 'kr', 'South Korea'), 'tw': ('google.com.tw', 'zh-TW', 'tw', 'Taiwan'),
    'hk': ('google.com.hk', 'zh-TW', 'hk', 'Hong Kong'), 'id': ('google.co.id', 'id', 'id', 'Indonesia'),
    'th': ('google.co.th', 'th', 'th', 'Thailand'), 'vn': ('google.com.vn', 'vi', 'vn', 'Vietnam'),
    'br': ('google.com.br', 'pt-BR', 'br', 'Brazil'), 'mx': ('google.com.mx', 'es', 'mx', 'Mexico'),
    'ar': ('google.com.ar', 'es', 'ar', 'Argentina'), 'cl': ('google.cl', 'es', 'cl', 'Chile'),
    'co': ('google.com.co', 'es', 'co', 'Colombia'), 'ua': ('google.com.ua', 'uk', 'ua', 'Ukraine'),
}
SORTS = {'price_asc': (1, 'Price: low to high'), 'price_desc': (2, 'Price: high to low'), 'rating': (3, 'Rating: High to low')}
_UULE_KEY = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'


def uule(name: str) -> str:
    b = name.encode()
    return 'w+CAIQICI' + _UULE_KEY[len(b) % 64] + base64.b64encode(b).decode()


def shoprs(query: str, sort: str | None = None, pmin: float | None = None, pmax: float | None = None) -> str | None:
    """Encode Google's Shopping filter token for a sort order and/or a price range (in the local currency)."""
    if not sort and pmin is None and pmax is None:
        return None
    f: list = [(1, 1)]
    pr = None
    if pmin is not None or pmax is not None:
        pr = []
        if pmin is not None:
            pr.append((1, float(pmin) * 1e6))
        if pmax is not None:
            pr.append((2, float(pmax) * 1e6))
        pr.append((3, 1))
        f.append((2, [(2, pr)]))
    if sort:
        n, label = SORTS[sort]
        f += [(3, 23), (5, query), (6, [(1, 23), (2, label), (5, [(2, 1), (3, 1)]), (10, n)]), (12, 2), (17, n)]
    else:
        f += [(3, 5), (5, query), (6, [(1, 5), (2, 'Price'), (3, 2), (4, [(2, pr)]), (5, [(3, 1)])]), (12, 2)]
    return b64e(enc(f))


def search_url(query: str, country: str, hl: str, start: int = 0, sort: str | None = None,
               pmin: float | None = None, pmax: float | None = None, extra: dict | None = None) -> str:
    dom, _, gl, loc = COUNTRIES[country]
    p = {'q': query, 'udm': '28', 'hl': hl, 'gl': gl}
    tok = shoprs(query, sort, pmin, pmax)
    if extra and extra.get('shoprs') and not tok:
        tok = extra['shoprs']
    if tok:
        p['shoprs'] = tok
    if start:
        p['start'] = str(start)
    # GOOGLE_SERP proxy requires plain http:// (it upgrades to HTTPS itself)
    return f'http://www.{dom}/search?' + urlencode(p) + '&uule=' + uule(loc)


def parse_google_url(url: str) -> dict | None:
    """A Google Shopping URL pasted by the user -> {query, country?, hl?, shoprs?}."""
    try:
        u = urlsplit(url.strip())
    except ValueError:
        return None
    if 'google.' not in (u.hostname or ''):
        return None
    q = parse_qs(u.query)
    query = (q.get('q') or [''])[0].strip()
    if not query:
        return None
    host = (u.hostname or '').removeprefix('www.')
    country = next((c for c, v in COUNTRIES.items() if v[0] == host), None)
    gl = (q.get('gl') or [''])[0].lower()
    if gl:
        country = 'gb' if gl == 'uk' else (gl if gl in COUNTRIES else country)
    return {'query': query, 'country': country, 'hl': (q.get('hl') or [None])[0], 'shoprs': (q.get('shoprs') or [None])[0]}
