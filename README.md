# Google Shopping Scraper & API: Product Prices, Merchants, Ratings and Reviews in 46 Countries

[![Run on Apify](https://img.shields.io/badge/Run%20on-Apify-1f6feb?logo=apify)](https://apify.com/manageable_gully/google-shopping-scraper) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Run it in the cloud with no setup:** [Google Shopping Scraper: Prices, Merchants & Reviews on the Apify Store](https://apify.com/manageable_gully/google-shopping-scraper).  
> Pay only per result, export to JSON/CSV/Excel, schedule runs and call it from the API.
<!-- Note: the Apify Store page goes live once the Actor is published. -->
<!-- AFFILIATE_LINK_PLACEHOLDER: replace the Apify links above with the affiliate link when available -->

Scrape **Google Shopping** results for any search in 46 countries and get clean product rows: title, brand, price, old price and discount, currency, merchant, rating, exact review count, shipping, returns, condition, image and the Google product page link. Sort by price or rating, filter by a price range, and pull hundreds of products per search. No Google account, no API key.

## What you can use it for
- **Price monitoring and competitor tracking:** schedule a daily run for your product names and see who sells them, at what price and with what discount.
- **E-commerce and dropshipping research:** find the cheapest sellers, typical price ranges and best-rated products for a niche (`sortBy: price_asc` or `rating`).
- **Brands and MAP enforcement:** list every merchant showing your brand on Google Shopping and spot prices below your minimum advertised price.
- **Market and assortment analysis:** compare brands, merchants and price points for a category across the US, UK, Germany, France, Japan, Brazil and 40 more countries.
- **Marketing and PPC teams:** check which stores and prices appear for your Shopping keywords before you change bids.
- **AI agents and dashboards:** clean JSON with numeric prices and ISO currencies, ready for an LLM, Google Sheets or a BI tool.

## How to use it
1. Type your searches under **Search queries**, e.g. `air fryer` or `sony wh-1000xm5`.
2. Pick the **country**, how many products you want per search, and optionally a **sort order** and **price range**.
3. Click **Start**. A 100-product search usually takes under a minute.
4. Export to CSV, Excel or Google Sheets, or schedule the run daily for price tracking.

## Features
- **Any search, any of 46 countries:** google.com, google.co.uk, google.de, google.fr, google.co.jp, google.com.br, google.co.in and more. Prices come in the local currency from local merchants (the Actor pins the location, so you never get another country's results by accident).
- **The fields that matter for price research:** numeric `price` and `oldPrice`, `discountPercent`, ISO `currency`, `merchant` (or `multipleSellers` with a "from" price), `rating`, **exact `reviewsCount`** (not "1.6K"), `brand`, `shipping` / `freeShipping`, `returns`, `condition`.
- **Sort and filter like the Google UI:** relevance, price low to high, price high to low, rating; min and max price.
- **Depth:** Google shows about 30-40 new products per page. The Actor pages through the results and, when you ask for more than one sort order gives, also reads the other sort orders and merges the new products.
- **Paste Google Shopping URLs:** set filters in your browser, copy the URL into `startUrls`, and the Actor uses the same search.
- **Reliable:** every page is retried with fresh proxy sessions until it holds real product cards in the expected currency. Duplicates, filtered-out and failed results are never charged.

## Input
| Field | Type | Description |
|---|---|---|
| `queries` | array | Searches, e.g. `air fryer`, `nike air max 90`. |
| `countryCode` | string | Google Shopping country (default `us`). |
| `maxResultsPerQuery` | integer | Products per search, 1-1000 (default 100). |
| `sortBy` | string | `relevance`, `price_asc`, `price_desc` or `rating`. |
| `minPrice` / `maxPrice` | integer | Price range in the local currency. |
| `skipUsed` | boolean | Drop used and refurbished products. |
| `startUrls` | array | Google Shopping search URLs (query, country and filters are read from the URL). |
| `languageCode` | string | Interface language, default = the country's language. |
| `fillWithOtherSorts` | boolean | Go deeper with other sort orders when Google runs out (default on). |
| `maxResultsTotal` | integer | Stop the whole run after this many products (0 = no limit). |

Example:
```json
{
  "queries": ["air fryer", "robot vacuum"],
  "countryCode": "us",
  "maxResultsPerQuery": 200,
  "sortBy": "price_asc",
  "minPrice": 50,
  "maxPrice": 300
}
```

## Output
One dataset item per product:
```json
{
  "query": "air fryer",
  "country": "US",
  "position": 2,
  "productId": "286443961521812992",
  "catalogId": "5306024426597561701",
  "groupId": "5961847025112641569",
  "offerId": "10270790825225325383",
  "title": "Mainstays 2.2 QT Air Fryer",
  "brand": "Mainstays",
  "price": 29.98,
  "priceText": "$29.98",
  "oldPrice": null,
  "discountPercent": null,
  "currency": "USD",
  "merchant": "Walmart",
  "multipleSellers": true,
  "rating": 4.3,
  "reviewsCount": 1571,
  "shipping": null,
  "freeShipping": false,
  "returns": "Free 90-day returns",
  "condition": "new",
  "image": "https://encrypted-tbn0.gstatic.com/shopping?q=tbn:ANd9GcRbKHRR1x...",
  "productUrl": "https://www.google.com/search?ibp=oshop&q=air+fryer&prds=catalogid:5306024426597561701,...&udm=28",
  "priceIsFrom": false,
  "labels": [],
  "sortOrder": "relevance",
  "googleShoppingUrl": "https://www.google.com/search?q=air+fryer&udm=28&hl=en&gl=us",
  "scrapedAt": "2026-10-17T11:20:00Z"
}
```
Export to JSON, CSV, Excel or Google Sheets. Run statistics are saved to the `OUTPUT` record of the key-value store.

## Pricing
Pay per event, no monthly rent: **$0.0025 per product** (**$2.50 per 1,000**), plus $0.005 per run start.

| Example | Cost |
|---|---|
| 100 products | $0.255 |
| 1,000 products | $2.50 |
| 10,000 products | $25.00 |
| Daily price check: 20 searches x 50 products for 30 days | $75.15 |

You can set a **maximum cost per run** in the run options; the Actor stops cleanly when it is reached. New to Apify? The free plan includes $5 of platform credit every month, so you can try this Actor at no cost.

## API, integrations and AI agents (MCP)
Run it from your own code with the [Apify API](https://docs.apify.com/api/v2) and get the results in one call:
```bash
curl -X POST "https://api.apify.com/v2/acts/manageable_gully~google-shopping-scraper/run-sync-get-dataset-items?token=<YOUR_APIFY_TOKEN>" \
  -H "Content-Type: application/json" -d @input.json
```
```python
from apify_client import ApifyClient
run = ApifyClient("<YOUR_APIFY_TOKEN>").actor("manageable_gully/google-shopping-scraper").call(run_input={...})
```
- **No-code:** use the Apify app in **n8n, Make or Zapier** ("Run Actor", then "Get dataset items"), or send results to Google Sheets, Slack or a webhook.
- **AI agents (MCP):** add `https://mcp.apify.com?tools=manageable_gully/google-shopping-scraper` to Claude, Cursor, VS Code or any MCP client and the agent can call this Actor as a tool.
- **Schedules:** run it hourly, daily or weekly from Apify Console.

## FAQ
**Is there an official Google Shopping API?** Google has the Content API for your own Merchant Center products, but no public API for Shopping search results. This Actor reads the public Google Shopping pages, without a Google account.

**Which countries are supported?** 46 countries, including the US, UK, Canada, Australia, India, Germany, France, Spain, Italy, Netherlands, Poland, Sweden, Japan, Korea, Brazil, Mexico, Israel, UAE and Turkey. Results are pinned to the selected country, so prices are always in its local currency.

**Does it return the merchant's own product link?** It returns `productUrl`, Google's product page for the item, which lists every store's offer and links to it. The merchant name is in `merchant`; when several stores sell the item, `multipleSellers` is `true` and the price is the lowest one ("from" price, `priceIsFrom`).

**Why do some products have no rating?** Google shows ratings only for products with reviews. Those fields are `null`.

**How many products can I get per search?** Usually 100-300 for popular searches, depending on the country and query. Google stops paging after a while; `fillWithOtherSorts` adds more by reading the price and rating sort orders.

**Is the price filter exact?** Google treats it as a strong hint. With `strictPriceFilter` on (default), products outside your range are removed and not charged.

**Do I pay for duplicates or failed pages?** No. You pay only for unique products saved to the dataset. A search that Google blocks even after retries costs nothing beyond the run start.

**Is scraping Google Shopping legal?** The Actor reads public search result pages, without logging in. You are responsible for how you use the data; check the laws that apply to you and Google's terms.

**Can AI agents use it?** Yes. It is available as a tool through the Apify MCP server (`https://mcp.apify.com?tools=manageable_gully/google-shopping-scraper`) and the Apify API, and it returns structured JSON that agents can read directly.

**Can AI agents use it?** Yes. It is available as a tool through the Apify MCP server (`https://mcp.apify.com?tools=manageable_gully/google-shopping-scraper`) and the Apify API, and it returns structured JSON that agents can read directly.

## More tools from WebIntel Tools
- [Google Jobs Scraper](https://apify.com/manageable_gully/google-jobs-scraper): Google for Jobs listings with salaries and apply links
- [Website Tech Stack Detector](https://apify.com/manageable_gully/website-tech-detector): BuiltWith/Wappalyzer-style tech stack lookup in bulk
- [Product Hunt Scraper](https://apify.com/manageable_gully/product-hunt-scraper): daily, weekly and monthly Product Hunt launches with websites
- [Web Page to Markdown](https://apify.com/manageable_gully/page-to-markdown): clean Markdown and RAG chunks from any URL, for LLMs

See [all WebIntel Tools Actors](https://apify.com/manageable_gully).

*Made by WebIntel Tools. This Actor was built and is maintained with AI assistance. Report issues on the Issues tab; they are monitored daily.*

## Run from source
This repository is the full source of the [Google Shopping Scraper: Prices, Merchants & Reviews](https://apify.com/manageable_gully/google-shopping-scraper) Actor.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest
# run locally with the Apify CLI (https://docs.apify.com/cli):
apify run --input '{...}'
```

Deploy your own copy with `apify push`. The easiest way to use it is the hosted version on the [Apify Store](https://apify.com/manageable_gully/google-shopping-scraper).

<!-- AFFILIATE_LINK_PLACEHOLDER: "New to Apify? Sign up here" link goes here -->

## License
MIT, see [LICENSE](LICENSE).
