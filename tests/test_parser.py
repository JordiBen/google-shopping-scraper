import gzip
import pathlib

import pytest

from src.google import parse_google_url, search_url, shoprs
from src.main import InputError, parse_input
from src.parser import has_products, is_blocked, parse_count, parse_number, parse_price, parse_products
from src.pb import b64d, dec

FX = pathlib.Path(__file__).parent / 'fixtures'
CASES = {  # fixture: (country, hl, gl, domain, expected currency, min products)
    'us_air_fryer': ('us', 'en', 'us', 'google.com', 'USD', 40),
    'us_air_fryer_price_asc': ('us', 'en', 'us', 'google.com', 'USD', 35),
    'us_air_fryer_50_90': ('us', 'en', 'us', 'google.com', 'USD', 35),
    'fr_casque': ('fr', 'fr', 'fr', 'google.fr', 'EUR', 40),
    'jp_headphones': ('jp', 'ja', 'jp', 'google.co.jp', 'JPY', 40),
    'gb_running_shoes': ('gb', 'en', 'uk', 'google.co.uk', 'GBP', 35),
    'de_kaffeemaschine': ('de', 'de', 'de', 'google.de', 'EUR', 35),
    'br_notebook': ('br', 'pt-BR', 'br', 'google.com.br', 'BRL', 30),
    'in_smartphone': ('in', 'en', 'in', 'google.co.in', 'INR', 35),
}


def load(name):
    p = FX / f'{name}.html.gz'
    if not p.exists():
        pytest.skip(f'fixture {p.name} not present (see tests/README.md)')
    return gzip.decompress(p.read_bytes()).decode()


@pytest.mark.parametrize('name', list(CASES))
def test_fixture_pages(name):
    cc, hl, gl, dom, cur, n = CASES[name]
    html = load(name)
    assert has_products(html) and not is_blocked(html)
    rows = parse_products(html, query='q', country=cc, hl=hl, gl=gl, domain=dom)
    assert len(rows) >= n
    keys = [r['groupId'] or r['catalogId'] or r['offerId'] for r in rows]
    assert len(keys) == len(set(keys)), 'duplicates'
    priced = [r for r in rows if r['price'] is not None]
    assert len(priced) >= 0.97 * len(rows)
    assert all(r['currency'] == cur for r in priced)
    assert all(r['title'] and r['productUrl'] and r['productUrl'].startswith(f'https://www.{dom}/search?ibp=oshop') for r in rows)
    assert sum(1 for r in rows if r['image']) >= 0.8 * len(rows)
    assert sum(1 for r in rows if r['merchant'] or r['multipleSellers']) == len(rows)
    rated = [r for r in rows if r['rating'] is not None]
    assert all(0 < r['rating'] <= 5 for r in rated)
    assert all(isinstance(r['reviewsCount'], int) for r in rated if r['reviewsCount'] is not None)


def test_sorted_and_price_filtered_pages():
    rows = parse_products(load('us_air_fryer_price_asc'), query='q', country='us', hl='en', gl='us', domain='google.com')
    prices = [r['price'] for r in rows if r['price'] is not None]
    assert prices == sorted(prices)
    rows = parse_products(load('us_air_fryer_50_90'), query='q', country='us', hl='en', gl='us', domain='google.com')
    inside = [r for r in rows if r['price'] is not None and 50 <= r['price'] <= 90]
    assert len(inside) >= 0.9 * len(rows)


def test_end_of_results_page():
    html = load('us_end_of_results')
    assert not has_products(html) and not is_blocked(html)


def test_us_details():
    rows = parse_products(load('us_air_fryer'), query='air fryer', country='us', hl='en', gl='us', domain='google.com')
    r = next(x for x in rows if x['title'] == 'Mainstays 2.2 QT Air Fryer')
    assert r['price'] == 29.98 and r['merchant'] == 'Walmart' and r['rating'] == 4.3 and r['reviewsCount'] == 1571
    assert r['brand'] == 'Mainstays' and r['image'].startswith('https://encrypted-tbn')
    assert 'catalogid:5306024426597561701' in r['productUrl'] and 'gpcid:5961847025112641569' in r['productUrl']
    assert any(x['oldPrice'] and x['discountPercent'] for x in rows)
    assert any(x['freeShipping'] for x in rows)


def test_numbers():
    assert parse_number('1,299.99') == 1299.99
    assert parse_number('1.299,99', ',') == 1299.99
    assert parse_number('2.499,00', ',') == 2499.0
    assert parse_number('12,800') == 12800
    assert parse_number('1 299,99', ',') == 1299.99
    assert parse_price('R$ 2.499,00', 'br') == (2499.0, 'BRL')
    assert parse_price('49,00 €', 'fr') == (49.0, 'EUR')
    assert parse_price('$29.98', 'us') == (29.98, 'USD')
    assert parse_price('$29.98', 'au') == (29.98, 'AUD')
    assert parse_price('£160.65', 'gb') == (160.65, 'GBP')
    assert parse_price('￥59,000+', 'jp') == (59000.0, 'JPY')
    assert parse_price('₹74,999', 'in') == (74999.0, 'INR')
    assert parse_count('(1.6K)') == 1600 and parse_count('(33 k)') == 33000 and parse_count('(2314)') == 2314


def test_blocked():
    assert is_blocked('<html>Our systems have detected unusual traffic from your computer network /sorry/index</html>')
    assert is_blocked('', 429)


def test_shoprs_roundtrip():
    assert shoprs('air fryer', 'price_asc') == 'CAEYFyoJYWlyIGZyeWVyMh4IFxISUHJpY2U6IGxvdyB0byBoaWdoKgQQARgBUAFgAogBAQ'
    f = dec(b64d(shoprs('air fryer', None, 50, 90)))
    assert f[1][0] == 2 and f[3] == (5, 'air fryer')
    assert shoprs('x') is None
    u = search_url('air fryer', 'gb', 'en', 10, 'rating')
    assert u.startswith('http://www.google.co.uk/search?') and 'udm=28' in u and 'start=10' in u and 'gl=uk' in u and 'uule=' in u


def test_input():
    c = parse_input({'queries': ['air fryer', 'Air  Fryer', ''], 'countryCode': 'UK', 'maxResultsPerQuery': 5000})
    assert len(c['searches']) == 1 and c['country'] == 'gb' and c['maxPerQuery'] == 1000 and c['hl'] == 'en'
    c = parse_input({'startUrls': [{'url': 'https://www.google.de/search?q=kaffee&tbm=shop&hl=de'}]})
    assert c['searches'][0]['country'] == 'de' and c['searches'][0]['query'] == 'kaffee'
    with pytest.raises(InputError):
        parse_input({})
    with pytest.raises(InputError):
        parse_input({'queries': ['x'], 'minPrice': 10, 'maxPrice': 5})
    with pytest.raises(InputError):
        parse_input({'queries': ['x'], 'countryCode': 'zz'})
    assert parse_google_url('https://example.com/?q=x') is None


def test_page_region():
    from src.parser import page_region
    assert page_region(load('us_air_fryer')) == 'US'
    assert page_region(load('gb_running_shoes')) == 'GB'
    assert page_region(load('de_kaffeemaschine')) == 'DE'
    assert page_region('<html></html>') is None
