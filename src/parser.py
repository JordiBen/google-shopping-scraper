"""Parse Google Shopping (udm=28) result pages into product rows.

Anchors: product wrappers carry data-cid/data-gid/data-oid/data-iid/data-pid; each wrapper references a JSON entry
(jsdata key) whose base64 protobuf holds title, brand, exact review count, rating and the full-size image URL.
Price, merchant, delivery and badges come from the card itself (aria-labels and text), which works for every locale.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

import lxml.html
from lxml import etree

from .pb import b64d, dec

BLOCK_MARKERS = ('/sorry/index', 'unusual traffic from your computer', 'detected unusual traffic', 'our systems have detected')
CUR_SYMBOLS = {'$': 'USD', '€': 'EUR', '£': 'GBP', '₹': 'INR', '¥': 'JPY', '￥': 'JPY', '₪': 'ILS', '₩': 'KRW', 'R$': 'BRL', 'A$': 'AUD',
               'C$': 'CAD', 'CA$': 'CAD', 'AU$': 'AUD', 'NZ$': 'NZD', 'MX$': 'MXN', 'zł': 'PLN', 'kr': 'SEK', 'CHF': 'CHF', 'Fr.': 'CHF',
               '₺': 'TRY', 'R': 'ZAR', 'AED': 'AED', 'S$': 'SGD', 'HK$': 'HKD', '₱': 'PHP', 'RM': 'MYR', 'Rp': 'IDR', '₫': 'VND', '฿': 'THB',
               'Kč': 'CZK', 'Ft': 'HUF', 'lei': 'RON', 'COP': 'COP', 'CLP': 'CLP', 'S/': 'PEN', 'SAR': 'SAR', 'NT$': 'TWD', 'E£': 'EGP'}
# Local currency per country: "$" is ambiguous, so the country decides.
COUNTRY_CURRENCY = {'us': 'USD', 'ca': 'CAD', 'au': 'AUD', 'nz': 'NZD', 'mx': 'MXN', 'sg': 'SGD', 'hk': 'HKD', 'tw': 'TWD', 'ar': 'ARS',
                    'cl': 'CLP', 'co': 'COP', 'br': 'BRL', 'gb': 'GBP', 'ie': 'EUR', 'de': 'EUR', 'at': 'EUR', 'fr': 'EUR', 'es': 'EUR',
                    'it': 'EUR', 'nl': 'EUR', 'be': 'EUR', 'pt': 'EUR', 'fi': 'EUR', 'gr': 'EUR', 'sk': 'EUR', 'ch': 'CHF', 'se': 'SEK',
                    'no': 'NOK', 'dk': 'DKK', 'pl': 'PLN', 'cz': 'CZK', 'hu': 'HUF', 'ro': 'RON', 'tr': 'TRY', 'il': 'ILS', 'ae': 'AED',
                    'sa': 'SAR', 'in': 'INR', 'jp': 'JPY', 'kr': 'KRW', 'id': 'IDR', 'my': 'MYR', 'ph': 'PHP', 'th': 'THB', 'vn': 'VND',
                    'za': 'ZAR', 'eg': 'EGP', 'pe': 'PEN', 'ua': 'UAH'}
PRICE_RE = re.compile(r'(?P<pre>[^\d\s.,]{0,4})\s?(?P<num>\d[\d\s.,\u202f\u00a0]*)\s?(?P<post>[^\d\s.,]{0,4})')
DISCOUNT_RE = re.compile(r'(\d{1,2})\s?%')
STAR_RE = re.compile(r'(\d(?:[.,]\d)?)')
KEY_RE = re.compile(r'"([A-Za-z0-9_-]{8,40})":\["\d{0,25}","\d{0,25}","\d{0,25}","\d{6,25}","C')


def norm(s: str | None) -> str:
    return re.sub(r'\s+', ' ', (s or '').replace('\u00a0', ' ').replace('\u202f', ' ')).strip()


def is_blocked(html: str, status: int = 200) -> bool:
    if status in (302, 403, 429, 503):
        return True
    if 'data-cid' in html:
        return False
    low = html[:300_000].lower()
    if len(html) < 150_000 and (any(m in low for m in BLOCK_MARKERS) or 'enablejs' in low):
        return True
    return False


def has_products(html: str) -> bool:
    return 'data-cid=' in html and 'data-oid=' in html


def parse_number(num: str, decimal_hint: str | None = None) -> float | None:
    """'1,299.99' / '1.299,99' / '1 299,99' / '12,345' / '¥12,800' -> float."""
    n = re.sub(r'[\s\u00a0\u202f\']', '', num).strip('.,')
    if not n:
        return None
    last_dot, last_comma = n.rfind('.'), n.rfind(',')
    if last_dot >= 0 and last_comma >= 0:
        dec_sep = '.' if last_dot > last_comma else ','
    elif last_comma >= 0:
        tail = n[last_comma + 1:]
        dec_sep = ',' if (len(tail) != 3 or n.count(',') == 1 and decimal_hint == ',') and n.count(',') == 1 else None
        if len(tail) == 3 and decimal_hint != ',':
            dec_sep = None
    elif last_dot >= 0:
        tail = n[last_dot + 1:]
        dec_sep = '.' if (len(tail) != 3 or n.count('.') == 1 and decimal_hint == '.') and n.count('.') == 1 else None
        if len(tail) == 3 and decimal_hint == ',':
            dec_sep = None
    else:
        dec_sep = None
    if dec_sep:
        thou = ',' if dec_sep == '.' else '.'
        n = n.replace(thou, '').replace(dec_sep, '.')
    else:
        n = n.replace(',', '').replace('.', '')
    try:
        return float(n)
    except ValueError:
        return None


DECIMAL_COMMA = {'de', 'at', 'fr', 'es', 'it', 'nl', 'be', 'pt', 'fi', 'gr', 'sk', 'br', 'se', 'no', 'dk', 'pl', 'cz', 'hu', 'ro', 'tr', 'ar',
                 'cl', 'co', 'id', 'vn', 'za', 'ua', 'pe'}


def parse_price(text: str, country: str) -> tuple[float | None, str | None]:
    t = norm(text)
    m = PRICE_RE.search(t)
    if not m:
        return None, None
    hint = ',' if country in DECIMAL_COMMA else '.'
    value = parse_number(m.group('num'), hint)
    sym = (m.group('pre') or m.group('post') or '').strip()
    cur = None
    if sym:
        cur = CUR_SYMBOLS.get(sym)
        if sym in ('$', 'kr', 'R') or cur is None:
            local = COUNTRY_CURRENCY.get(country)
            if sym == '$' and local and local.endswith(('D', 'N', 'P', 'S')) and local not in ('SGD',) or sym == '$' and local in ('SGD', 'MXN', 'ARS', 'CLP', 'COP', 'TWD', 'HKD'):
                cur = local
            elif sym == 'kr' and local in ('SEK', 'NOK', 'DKK'):
                cur = local
            elif sym == 'R' and local == 'ZAR':
                cur = 'ZAR'
            elif cur is None:
                cur = local if sym and len(sym) <= 4 else None
    return value, cur


def _blob_info(raw: str) -> dict:
    out: dict = {}
    try:
        fields = dec(b64d(raw))
    except Exception:  # noqa: BLE001 - layout drift: fall back to HTML-only fields
        return out
    for f, v in fields:
        if f == 1 and isinstance(v, str):
            out['title'] = v
        elif f == 3 and isinstance(v, str):
            out['brand'] = v
        elif f == 4 and isinstance(v, list):
            for g, w in v:
                if g == 1 and isinstance(w, int):
                    out['reviewsCount'] = w
                elif g == 6 and isinstance(w, str):
                    try:
                        out['rating'] = float(w.replace(',', '.'))
                    except ValueError:
                        pass
        elif f in (35, 38) and 'image' not in out:
            m = re.search(r"https://encrypted-tbn\d\.gstatic\.com/shopping\?q=tbn:[A-Za-z0-9_-]+", repr(v))
            if m:
                out['image'] = m.group(0)
    return out


def data_entries(html: str) -> dict[str, dict]:
    """jsdata key -> {ids..., blob info} from the inline JSON map."""
    out: dict[str, dict] = {}
    dec_ = json.JSONDecoder()
    for m in KEY_RE.finditer(html):
        try:
            arr, _ = dec_.raw_decode(html, m.end(1) + 2)
        except ValueError:
            continue
        if not isinstance(arr, list) or len(arr) < 7:
            continue
        info = _blob_info(arr[4]) if isinstance(arr[4], str) else {}
        info.update(iid=arr[0], cid=arr[1], pid=arr[2], oid=arr[3], gid=arr[5] if len(arr) > 5 else None,
                    mid=arr[6] if len(arr) > 6 else None, pvt=arr[8] if len(arr) > 8 and isinstance(arr[8], str) else None)
        out[m.group(1)] = info
    return out


def product_url(q: str, e: dict, hl: str, gl: str, domain: str) -> str | None:
    if not e.get('cid') and not e.get('gid') and not e.get('oid'):
        return None
    prds = []
    keys = (('cid', 'catalogid'), ('oid', 'headlineOfferDocid'), ('iid', 'imageDocid'), ('gid', 'gpcid'), ('mid', 'mid'))
    if not e.get('cid') and not e.get('gid'):
        keys = (('oid', 'headlineOfferDocid'), ('iid', 'imageDocid'), ('pid', 'productDocid'), ('mid', 'mid'))
    for k, name in keys:
        if e.get(k) and e.get(k) != '0':
            prds.append(f'{name}:{e[k]}')
    prds.append(f"pvt:{e.get('pvt') or 'hg'}")
    return (f'https://www.{domain}/search?ibp=oshop&q={quote_plus(q)}&prds={",".join(prds)}'
            f'&hl={hl}&gl={gl}&udm=28')


def _cls(name: str) -> str:
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {name} ')"


def _txt(el) -> str:
    return norm(el.text_content()) if el is not None else ''


def _first(el, xp):
    r = el.xpath(xp)
    return r[0] if r else None


def _card_fields(w, country: str) -> dict:
    d: dict = {}
    t = _first(w, ".//div[@role='img'][@title]")
    if t is not None:
        d['title'] = norm(t.get('title')).rstrip('. ').strip()
    else:
        i = _first(w, './/img[@alt]')
        if i is not None and norm(i.get('alt')):
            d['title'] = norm(i.get('alt')).rstrip('. ').strip()
    prices = []
    grp = _first(w, ".//div[@role='group'][@aria-label]")
    if grp is not None:
        for sp in grp.iter('span'):
            if sp.find('.//span') is not None:
                continue
            tx = _txt(sp)
            if tx and re.search(r'\d', tx):
                prices.append(tx)
    d['_prices'] = prices
    m = _first(w, f".//span[{_cls('WJMUdc')}]")
    if m is not None:
        d['merchant'] = _txt(m)
    more = _first(w, f".//span[{_cls('Ludoze')}]")
    d['multipleSellers'] = bool(more is not None and _txt(more))
    d['_moreText'] = _txt(more) if more is not None else None
    lines = []
    for el in w.xpath(f".//div[{_cls('mhqZ2c')}] | .//*[{_cls('l9Ycjb')}] | .//div[{_cls('wuglHf')}]/div"):
        tx = _txt(el)
        if tx and tx not in lines:
            lines.append(tx)
    d['_lines'] = lines
    r = _first(w, f".//span[{_cls('yi40Hd')}]")
    if r is not None:
        d['_ratingText'] = _txt(r)
    rc = _first(w, f".//span[{_cls('RDApEe')}]")
    if rc is not None:
        d['_reviewsText'] = _txt(rc)
    badge = _first(w, ".//*[contains(@class, 'MRdnUb')]")
    if badge is not None:
        d['badge'] = _txt(badge)
    return d


SHIP_RE = re.compile(r'deliver|shipping|livraison|versand|lieferung|envío|envio|entrega|spedizione|consegna|verzending|bezorg|frete|配送|送料|dostaw|leverans|levering|toimitus|доставк|משלוח|teslimat|szállítás|doručen|livrare|delivery', re.I)
RET_RE = re.compile(r'return|retour|rückgabe|rücknahme|rücksend|devoluci|devoluç|reso|resi|返品|zwrot|retur|palautus|vrácen|החזר|iade|visszaküld', re.I)
USED_RE = re.compile(r'pre-owned|\bused\b|refurbished|renewed|reconditionn|gebraucht|occasion|usado|reacondicionado|ricondizionato|usato|reconditionné|generalüberholt|中古|używany|begagnad|second-hand', re.I)


RATING_LINE_RE = re.compile(r'^\d(?:[.,]\d)?\s*\(?\s*[\d.,]+\s*[kKmM千万]?\s*\)?$')
MULT = {'k': 1_000, 'K': 1_000, 'm': 1_000_000, 'M': 1_000_000, '千': 1_000, '万': 10_000}


def parse_count(txt: str | None) -> int | None:
    m = re.search(r'([\d.,\s]+)\s*([kKmM千万]?)', (txt or '').replace('\u00a0', ' ').replace('\u202f', ' '))
    if not m or not re.search(r'\d', m.group(1)):
        return None
    num = m.group(1).strip()
    if m.group(2):
        try:
            return int(round(float(num.replace(' ', '').replace(',', '.')) * MULT[m.group(2)]))
        except ValueError:
            return None
    try:
        return int(re.sub(r'[^\d]', '', num))
    except ValueError:
        return None


def _merge_cards(cards: list[dict]) -> dict:
    out: dict = {}
    for c in cards:
        for k, v in c.items():
            if k not in out or out[k] in (None, '', [], False):
                out[k] = v
    return out


DH_RE = re.compile(r"""\{id:'([^']+)'\},function\(\)\{jsl\.dh\(this\.id,"((?:[^"\\]|\\.)*)"\)""")


def js_unescape(s: str) -> str:
    s = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: '\\u00' + m.group(1), s).replace("\\'", "'")
    try:
        return json.loads('"' + s + '"')
    except ValueError:
        return s


def deferred_fragments(html: str) -> dict[str, str]:
    """Google lazy-renders many product cards: their HTML sits in jsl.dh(id, "...") script calls. id -> HTML."""
    out = {}
    for m in DH_RE.finditer(html):
        frag = m.group(2)
        if 'data-cid' in frag or 'FG68Ac' in frag or 'product-viewer' in frag:
            out[m.group(1)] = frag
    return out


def parse_products(html: str, *, query: str, country: str, hl: str, gl: str, domain: str) -> list[dict]:
    doc = lxml.html.fromstring(html)
    deferred = deferred_fragments(html)
    entries = data_entries(html)
    by_oid = {e['oid']: e for e in entries.values() if e.get('oid')}
    order: list[str] = []
    groups: dict[str, dict] = {}
    for w in doc.xpath('//div[@data-cid][@data-oid]'):
        cid, oid, gid = w.get('data-cid'), w.get('data-oid'), w.get('data-gid')
        if not norm(w.text_content()) and w.get('id') in deferred:
            try:
                w = lxml.html.fragment_fromstring(js_unescape(deferred[w.get('id')]), create_parent='div')
            except (etree.ParserError, ValueError):
                pass
        key = gid if gid and gid != '0' else (cid if cid and cid != '0' else oid)
        if not key:
            continue
        g = groups.get(key)
        if g is None:
            g = groups[key] = {'cid': cid, 'oid': oid, 'gid': gid, 'pid': w.get('data-pid'), 'entry': {}, 'cards': []}
            order.append(key)
        if not g['entry']:
            jd = _first(w, './/*[contains(@jsdata, ";_;")]')
            if jd is not None:
                k = jd.get('jsdata').split(';_;')[-1].split(';')[0].strip()
                g['entry'] = entries.get(k, {})
            if not g['entry']:
                g['entry'] = by_oid.get(oid, {})
        g['cards'].append(_card_fields(w, country))
    rows: list[dict] = []
    for key in order:
        g = groups[key]
        e, cid, oid, gid = g['entry'], g['cid'], g['oid'], g['gid']
        c = _merge_cards(g['cards'])
        title = e.get('title') or c.get('title')
        if not title:
            continue
        prices = c.get('_prices') or []
        price_txt = prices[0] if prices else None
        price, cur = parse_price(price_txt, country) if price_txt else (None, None)
        old_price = None
        for extra in prices[1:]:
            v, _ = parse_price(extra, country)
            if v and price and v > price:
                old_price = v
                break
        merchant = c.get('merchant')
        lines = [l for l in (c.get('_lines') or []) if l not in (title, merchant) and not (price_txt and price_txt in l)
                 and not RATING_LINE_RE.match(l) and not (merchant and l.startswith(merchant))]
        ship = next((l for l in lines if SHIP_RE.search(l) and not RET_RE.search(l)), None) or next((l for l in lines if SHIP_RE.search(l)), None)
        ret = next((l for l in lines if RET_RE.search(l) and l != ship), None)
        cond = 'used' if any(USED_RE.search(l) for l in lines + [title]) else 'new'
        disc = None
        for l in lines + [c.get('badge') or '']:
            mm = DISCOUNT_RE.search(l)
            if mm and len(l) < 25:
                disc = int(mm.group(1))
                break
        if disc is None and old_price and price:
            disc = round((1 - price / old_price) * 100)
        rating = e.get('rating')
        if rating is None and c.get('_ratingText'):
            try:
                rating = float(c['_ratingText'].replace(',', '.'))
            except ValueError:
                rating = None
        reviews = e.get('reviewsCount')
        if reviews is None and c.get('_reviewsText'):
            reviews = parse_count(c['_reviewsText'])
        rows.append({
            'productId': e.get('pid') or g['pid'] or None,
            'catalogId': cid if cid and cid != '0' else None,
            'groupId': gid if gid and gid != '0' else None,
            'offerId': oid or None,
            'title': title,
            'brand': e.get('brand'),
            'price': price,
            'priceText': price_txt,
            'oldPrice': old_price,
            'discountPercent': disc,
            'currency': cur,
            'merchant': merchant,
            'multipleSellers': bool(c.get('multipleSellers')),
            'rating': rating,
            'reviewsCount': reviews,
            'shipping': ship,
            'freeShipping': bool(ship and re.search(r'free|gratuit|kostenlos|gratis|grátis|gratuita|無料|darmo|ilmai|zdarma|ücretsiz|ingyenes|חינם', ship, re.I)),
            'returns': ret,
            'condition': cond,
            'image': e.get('image'),
            'productUrl': product_url(query, {**e, 'cid': e.get('cid') or cid, 'oid': e.get('oid') or oid, 'gid': e.get('gid') or gid}, hl, gl, domain),
            'priceIsFrom': bool(price_txt and price_txt.rstrip().endswith('+')),
            'labels': [l for l in lines if l not in (ship, ret) and not (c.get('multipleSellers') and l == c.get('_moreText'))][:6],
        })
    return rows


REGION_RE = re.compile(r'"MgUcDb":"([A-Za-z]{2})"')


def page_region(html: str) -> str | None:
    """Two-letter region Google localised the page for (e.g. 'US'), from the inline page config."""
    m = REGION_RE.search(html)
    return m.group(1).upper() if m else None


def total_hint(html: str) -> bool:
    """True when Google offers a 'More results' link (more pages may exist)."""
    return 'start=' in html and 'aria-label="More results"' in html
