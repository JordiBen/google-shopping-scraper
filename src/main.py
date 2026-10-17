"""Google Shopping Scraper: products, prices, merchants, ratings and reviews from Google Shopping (udm=28) by search query.

Fetching: plain HTTP through Apify's GOOGLE_SERP proxy (pinned to the chosen country with gl + uule), up to 5 attempts
per page with fresh proxy sessions. A page counts as valid only if it holds product cards priced in the expected
local currency, so results from a wrong-country exit are retried instead of being returned.
Pagination: start=10, 20, ... (each page adds ~30-40 new products); optional fill-up with other sort orders.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import random
import time
from collections import Counter

import httpx
from apify import Actor

from .google import COUNTRIES, SORTS, parse_google_url, search_url
from .parser import COUNTRY_CURRENCY, has_products, is_blocked, page_region, parse_products

PRODUCT_EVENT = 'product'
SERP_COST = 0.0025
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
MAX_PAGES = 30
NO_RESULTS_MARKERS = ('did not match any shopping results', 'no results found for', 'keine ergebnisse', 'aucun résultat',
                      'no se han encontrado resultados', 'nessun risultato', 'geen resultaten', 'did not match any documents')


class InputError(ValueError):
    pass


def _num(v, name):
    if v in (None, ''):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise InputError(f'"{name}" must be a number.') from None
    if f < 0:
        raise InputError(f'"{name}" cannot be negative.')
    return f


def parse_input(inp: dict) -> dict:
    cc = str(inp.get('countryCode') or 'us').lower().strip()
    if cc == 'uk':
        cc = 'gb'
    if cc not in COUNTRIES:
        raise InputError(f'Unsupported countryCode "{cc}". Supported: {", ".join(sorted(COUNTRIES))}.')
    hl = str(inp.get('languageCode') or '').strip() or COUNTRIES[cc][1]
    if not (2 <= len(hl) <= 5) or not hl[:2].isalpha():
        raise InputError('languageCode must look like "en", "de" or "pt-BR".')
    sort = str(inp.get('sortBy') or 'relevance')
    if sort not in ('relevance', *SORTS):
        raise InputError('sortBy must be relevance, price_asc, price_desc or rating.')
    pmin, pmax = _num(inp.get('minPrice'), 'minPrice'), _num(inp.get('maxPrice'), 'maxPrice')
    if pmin is not None and pmax is not None and pmin > pmax:
        raise InputError('minPrice is higher than maxPrice.')
    searches, seen = [], set()
    for q in inp.get('queries') or []:
        q = ' '.join(str(q or '').split())[:300]
        if q and (q.lower(), cc) not in seen:
            seen.add((q.lower(), cc))
            searches.append({'query': q, 'country': cc, 'hl': hl, 'shoprs': None})
    for u in inp.get('startUrls') or []:
        url = u.get('url') if isinstance(u, dict) else u
        g = parse_google_url(str(url or ''))
        if not g:
            raise InputError(f'Not a Google Shopping search URL: {str(url)[:120]}')
        c = g['country'] or cc
        if (g['query'].lower(), c, g['shoprs']) not in seen:
            seen.add((g['query'].lower(), c, g['shoprs']))
            searches.append({'query': g['query'], 'country': c, 'hl': g['hl'] or COUNTRIES[c][1], 'shoprs': g['shoprs']})
    if not searches:
        raise InputError('Add at least one search query in "queries" (e.g. "air fryer") or a Google Shopping URL in "startUrls".')
    return {
        'searches': searches, 'country': cc, 'hl': hl, 'sort': None if sort == 'relevance' else sort, 'minPrice': pmin, 'maxPrice': pmax,
        'maxPerQuery': int(min(max(int(inp.get('maxResultsPerQuery') or 100), 1), 1000)),
        'maxTotal': int(min(max(int(inp.get('maxResultsTotal') or 0), 0), 1_000_000)),
        'fillWithOtherSorts': bool(inp.get('fillWithOtherSorts', True)),
        'skipUsed': bool(inp.get('skipUsed', False)),
        'enforcePrice': bool(inp.get('strictPriceFilter', True)),
        'concurrency': int(min(max(int(inp.get('maxConcurrency') or 8), 1), 20)),
    }


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Run:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.stop = asyncio.Event()
        self.sem = asyncio.Semaphore(cfg['concurrency'])
        self.push_lock = asyncio.Lock()
        self.stats = {'requests': 0, 'blocked': 0, 'errors': 0, 'wrongCountryRetried': 0, 'emptyRetried': 0, 'pagesOk': 0,
                      'pagesEnd': 0, 'pagesFailed': 0, 'products': 0, 'filteredOut': 0, 'duplicates': 0, 'searchesWithProducts': 0,
                      'searchesNoResults': 0, 'searchesFailed': 0, 'cardsWithoutPrice': 0}
        self.t0 = time.time()
        self.timing = {'fetch': 0.0, 'parse': 0.0}
        self.wrong_cur: Counter = Counter()
        self.pcs: dict[str, object] = {}

    async def proxy_url(self, country: str) -> str | None:
        if country not in self.pcs:
            try:
                self.pcs[country] = await Actor.create_proxy_configuration(groups=['GOOGLE_SERP'], country_code=country.upper())
            except Exception as e:  # noqa: BLE001 - local runs without proxy access
                Actor.log.warning(f'GOOGLE_SERP proxy unavailable ({e}); fetching directly.')
                self.pcs[country] = None
        pc = self.pcs[country]
        return await pc.new_url() if pc else None

    async def fetch_page(self, s: dict, start: int, sort: str | None) -> tuple[str, list[dict]]:
        """Return (kind, rows). kind: ok | end | failed."""
        cfg = self.cfg
        url = search_url(s['query'], s['country'], s['hl'], start, sort, cfg['minPrice'], cfg['maxPrice'], {'shoprs': s['shoprs']})
        expect_cur = COUNTRY_CURRENCY.get(s['country'])
        empty_seen = 0
        for attempt in range(6):
            if self.stop.is_set():
                return 'failed', []
            async with self.sem:
                self.stats['requests'] += 1
                t_req = time.time()
                try:
                    async with httpx.AsyncClient(proxy=await self.proxy_url(s['country']), timeout=60, follow_redirects=False, headers={
                            'User-Agent': UA, 'Accept-Language': f"{s['hl']},en;q=0.7",
                            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}) as c:
                        r = await c.get(url)
                    html = r.text
                except (httpx.HTTPError, OSError) as e:
                    self.stats['errors'] += 1
                    Actor.log.debug(f'request error {type(e).__name__}')
                    html, r = None, None
                self.timing['fetch'] += time.time() - t_req
            if html is not None:
                if is_blocked(html, r.status_code):
                    self.stats['blocked'] += 1
                elif r.status_code != 200:
                    self.stats['errors'] += 1
                elif (region := page_region(html)) and region != s['country'].upper():
                    self.stats['wrongCountryRetried'] += 1  # proxy exit in another country: Google localised the page
                    self.wrong_cur[region] += 1
                elif has_products(html):
                    t_parse = time.time()
                    rows = await asyncio.to_thread(parse_products, html, query=s['query'], country=s['country'], hl=s['hl'],
                                                   gl=COUNTRIES[s['country']][2], domain=COUNTRIES[s['country']][0])
                    self.timing['parse'] += time.time() - t_parse
                    curs = Counter(x['currency'] for x in rows if x['currency'])
                    top = curs.most_common(1)[0][0] if curs else None
                    if rows and expect_cur and top and top != expect_cur and curs[top] > len(rows) * 0.6:
                        self.stats['wrongCountryRetried'] += 1  # proxy exit in another country: Google localised the page
                        self.wrong_cur[top] += 1
                        Actor.log.debug(f'page in {top}, expected {expect_cur}: retrying')
                    elif rows:
                        self.stats['pagesOk'] += 1
                        return 'ok', rows
                    else:
                        self.stats['emptyRetried'] += 1
                elif 'udm=28' in html or 'Google Shopping' in html[:5000] or '<title>' in html[:3000]:
                    # A normal Shopping page without product cards: end of results (or no results). Confirm once.
                    empty_seen += 1
                    low = html[:400_000].lower()
                    if empty_seen >= 2 or any(m in low for m in NO_RESULTS_MARKERS) or start > 0 and empty_seen >= 1 and attempt >= 1:
                        self.stats['pagesEnd'] += 1
                        return 'end', []
                    self.stats['emptyRetried'] += 1
                else:
                    self.stats['blocked'] += 1
            await asyncio.sleep(min(1.5 ** attempt, 10) * random.uniform(0.4, 1.0))
        self.stats['pagesFailed'] += 1
        return 'failed', []

    def keep(self, row: dict) -> bool:
        cfg = self.cfg
        if cfg['skipUsed'] and row['condition'] == 'used':
            return False
        if cfg['enforcePrice'] and (cfg['minPrice'] is not None or cfg['maxPrice'] is not None):
            p = row['price']
            if p is None or (cfg['minPrice'] is not None and p < cfg['minPrice']) or (cfg['maxPrice'] is not None and p > cfg['maxPrice']):
                return False
        return True

    async def run_search(self, s: dict, out: asyncio.Queue) -> None:
        cfg = self.cfg
        want = cfg['maxPerQuery']
        got: dict[str, dict] = {}
        any_ok = any_end = False
        failed = 0
        sorts = [cfg['sort']]
        if cfg['fillWithOtherSorts'] and not s['shoprs']:
            sorts += [x for x in (None, 'price_asc', 'price_desc', 'rating') if x != cfg['sort']]
        for si, sort in enumerate(sorts):
            if len(got) >= want or self.stop.is_set():
                break
            page, dry = 0, 0
            while len(got) < want and page < MAX_PAGES and not self.stop.is_set():
                remaining = want - len(got)
                wave = max(1, min(4, -(-remaining // 35)))
                starts = [(page + i) * 10 for i in range(wave)]
                page += wave
                results = await asyncio.gather(*(self.fetch_page(s, st, sort) for st in starts))
                added, ended = 0, False
                for kind, rows in results:
                    if kind == 'ok':
                        any_ok = True
                        for r in rows:
                            k = r['groupId'] or r['catalogId'] or r['offerId'] or r['title']
                            if k in got:
                                self.stats['duplicates'] += 1
                                continue
                            if not self.keep(r):
                                self.stats['filteredOut'] += 1
                                continue
                            if r['price'] is None:
                                self.stats['cardsWithoutPrice'] += 1
                            if len(got) < want:
                                r['_sort'] = sort or 'relevance'
                                got[k] = r
                                added += 1
                    elif kind == 'end':
                        any_end = ended = True
                    else:
                        failed += 1
                if ended:
                    break
                dry = dry + 1 if added == 0 else 0
                if dry >= 2:
                    break  # Google keeps returning products we already have: this sort order is exhausted
            if si == 0 and not got and (any_end or not any_ok):
                break  # nothing at all for the main search: other sort orders won't find anything either
        if got:
            self.stats['searchesWithProducts'] += 1
        elif any_ok or any_end:
            self.stats['searchesNoResults'] += 1
        else:
            self.stats['searchesFailed'] += 1
        ts = now_iso()
        dom, _, gl, _ = COUNTRIES[s['country']]
        page_url = f"https://www.{dom}/search?" + httpx.QueryParams({'q': s['query'], 'udm': '28', 'hl': s['hl'], 'gl': gl}).__str__()
        for pos, r in enumerate(got.values(), 1):
            sort_used = r.pop('_sort')
            await out.put({'query': s['query'], 'country': s['country'].upper(), 'position': pos, **r,
                           'sortOrder': sort_used, 'googleShoppingUrl': page_url, 'scrapedAt': ts})
        if len(got) < want:
            Actor.log.info(f'"{s["query"]}" ({s["country"]}): {len(got)} products (Google has no more for this search)'
                           if not failed else f'"{s["query"]}": {len(got)} products, {failed} page(s) failed after retries')

    def est_cost(self) -> float:
        return round(self.stats['requests'] * SERP_COST, 4)


async def probe(urls: list[str], country: str) -> None:
    pc = await Actor.create_proxy_configuration(groups=['GOOGLE_SERP'], country_code=country.upper())
    res = []
    for i, u in enumerate(urls[:10]):
        async with httpx.AsyncClient(proxy=await pc.new_url(), timeout=60, headers={'User-Agent': UA}) as c:
            r = await c.get(u.replace('https://', 'http://', 1))
        await Actor.set_value(f'PROBE-{i}', r.text, content_type='text/html')
        res.append({'i': i, 'url': u, 'status': r.status_code, 'len': len(r.text)})
    await Actor.set_value('PROBE', res)


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        if inp.get('_probeUrls'):  # maintainer diagnostics (not in the input schema): save raw pages
            await probe(inp['_probeUrls'], str(inp.get('_probeCountry') or 'us'))
            return
        try:
            cfg = parse_input(inp)
        except InputError as e:
            await Actor.fail(status_message=str(e))
            return
        run = Run(cfg)
        out: asyncio.Queue = asyncio.Queue()
        Actor.log.info(f"{len(cfg['searches'])} search(es), up to {cfg['maxPerQuery']} products each, "
                       f"sort={cfg['sort'] or 'relevance'}, price={cfg['minPrice']}-{cfg['maxPrice']}")

        async def producer():
            qsem = asyncio.Semaphore(max(1, cfg['concurrency'] // 2))

            async def one(s):
                async with qsem:
                    if not run.stop.is_set():
                        await run.run_search(s, out)
            await asyncio.gather(*(one(s) for s in cfg['searches']))
            await out.put(None)

        async def consumer():
            while True:
                r = await out.get()
                if r is None:
                    return
                if run.stop.is_set():
                    continue
                res = await Actor.push_data(r, charged_event_name=PRODUCT_EVENT)
                if res is not None and getattr(res, 'charged_count', 1) == 0 and getattr(res, 'event_charge_limit_reached', False):
                    run.stop.set()
                    continue
                run.stats['products'] += 1
                if res is not None and getattr(res, 'event_charge_limit_reached', False):
                    run.stop.set()
                if cfg['maxTotal'] and run.stats['products'] >= cfg['maxTotal']:
                    run.stop.set()
                if run.stats['products'] % 100 == 0:
                    await Actor.set_status_message(f"{run.stats['products']} products so far")

        await asyncio.gather(producer(), consumer())
        s = run.stats
        s['estimatedProxyCostUsd'] = run.est_cost()
        s['runSeconds'] = round(time.time() - run.t0, 1)
        s['wrongCountryRegions'] = dict(run.wrong_cur)
        s['avgFetchSecs'] = round(run.timing['fetch'] / max(1, s['requests']), 1)
        s['avgParseSecs'] = round(run.timing['parse'] / max(1, s['pagesOk'] + s['wrongCountryRetried']), 2)
        await Actor.set_value('OUTPUT', {'stats': s, 'input': {k: v for k, v in cfg.items()}})
        Actor.log.info(f'Stats: {s}')
        n = len(cfg['searches'])
        if s['products'] == 0 and s['searchesFailed'] == n:
            await Actor.fail(status_message='Google blocked every search in this run. Nothing was charged except the run start. Please retry later.')
            return
        msg = f"Done: {s['products']} products from {n} search{'es' if n != 1 else ''}"
        if s['searchesNoResults']:
            msg += f", {s['searchesNoResults']} with no Google Shopping results"
        if s['searchesFailed']:
            msg += f", {s['searchesFailed']} failed (not charged)"
        if run.stop.is_set() and not cfg['maxTotal']:
            msg += ' (stopped: max charge reached)'
        await Actor.set_status_message(msg, is_terminal=True)
