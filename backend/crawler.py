import re
import urllib.parse
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from playwright.sync_api import sync_playwright
import time
from typing import List, Dict, Set, Tuple, Any, Callable, Optional

# Known High Trust Think Tanks and Domains
HIGH_TRUST_DOMAINS = [
    "un.org", "un.int", "cfr.org", "csis.org", "brookings.edu", 
    "sipri.org", "carnegieendowment.org", "reuters.com", "apnews.com",
    "rand.org", "chathamhouse.org", "iiss.org", "crisisgroup.org",
    "loc.gov", "state.gov", "defense.gov", "whitehouse.gov",
    "hrw.org", "amnesty.org", "icrc.org", "law.harvard.edu",
    "yale.edu", "ox.ac.uk", "cam.ac.uk", "lse.ac.uk"
]

# Excluded domains (social media, sharing, etc.)
EXCLUDED_DOMAINS = [
    "facebook.com", "twitter.com", "linkedin.com", "youtube.com",
    "instagram.com", "pinterest.com", "reddit.com", "tumblr.com",
    "t.co", "goo.gl", "bit.ly", "wikimedia.org"
]

class GeopoliticalCrawler:
    def __init__(self, log_callback: Optional[Callable[[str], None]] = None):
        self.log_callback = log_callback
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5"
        }

    def _log(self, message: str):
        full_msg = f"[{time.strftime('%H:%M:%S')}] {message}"
        if self.log_callback:
            self.log_callback(full_msg)
        else:
            print(full_msg)

    def search_queries(self, queries: List[str], max_results: int = 10) -> List[Dict[str, Any]]:
        """Multi-provider search with 7 sources for maximum coverage."""
        candidates = []
        seen_urls = set()
        ddg_failed = False
        
        self._log(f"Starting 7-provider search for {len(queries)} queries...")
        
        # ── Provider 1: DuckDuckGo (with retry + backoff) ──
        self._log("[Provider 1/7] DuckDuckGo...")
        try:
            with DDGS() as ddgs:
                for q in queries:
                    self._log(f"  DDG: '{q}'")
                    for attempt in range(3):
                        try:
                            results = ddgs.text(q, max_results=max_results)
                            count = 0
                            for r in results:
                                url = r.get("href")
                                if url and url not in seen_urls:
                                    seen_urls.add(url)
                                    candidates.append({
                                        "url": url,
                                        "title": r.get("title", "Untitled"),
                                        "snippet": r.get("body", ""),
                                        "seed_query": q
                                    })
                                    count += 1
                            self._log(f"    Found {count} URLs (attempt {attempt+1})")
                            if count > 0:
                                break
                        except Exception as e:
                            self._log(f"    DDG attempt {attempt+1} failed: {e}")
                            time.sleep(2.0 * (attempt + 1))
                    time.sleep(1.5)
        except Exception as e:
            self._log(f"  DDG provider failed: {e}")
            ddg_failed = True

        ddg_count = len(candidates)
        self._log(f"  DDG total: {ddg_count} URLs")
        
        # ── Provider 2: Wikipedia API (always runs) ──
        self._log("[Provider 2/7] Wikipedia API...")
        wiki_candidates = self._search_wikipedia(queries, seen_urls)
        candidates.extend(wiki_candidates)
        self._log(f"  Wikipedia total: {len(wiki_candidates)} articles")
        
        # ── Provider 3: Bing Web Search (scraping, very reliable) ──
        self._log("[Provider 3/7] Bing Web Search...")
        bing_candidates = self._search_bing(queries, seen_urls)
        candidates.extend(bing_candidates)
        self._log(f"  Bing total: {len(bing_candidates)} URLs")
        
        # ── Provider 4: Google Scholar (academic papers) ──
        self._log("[Provider 4/7] Google Scholar...")
        scholar_candidates = self._search_google_scholar(queries, seen_urls)
        candidates.extend(scholar_candidates)
        self._log(f"  Scholar total: {len(scholar_candidates)} papers")
        
        # ── Provider 5: Archive.org (historical/archival documents) ──
        self._log("[Provider 5/7] Archive.org...")
        archive_candidates = self._search_archive_org(queries, seen_urls)
        candidates.extend(archive_candidates)
        self._log(f"  Archive.org total: {len(archive_candidates)} documents")
        
        # ── Provider 6: Google News RSS (current events) ──
        if ddg_count < 5 or ddg_failed:
            self._log("[Provider 6/7] Google News RSS (DDG weak, activating fallback)...")
            news_candidates = self._search_google_news(queries, seen_urls)
            candidates.extend(news_candidates)
            self._log(f"  Google News total: {len(news_candidates)} articles")
        else:
            self._log("[Provider 6/7] Google News RSS (skipped, DDG sufficient)")
        
        # ── Provider 7: Direct High-Trust Domain URLs ──
        self._log("[Provider 7/7] Constructing direct high-trust domain URLs...")
        direct_candidates = self._construct_direct_urls(queries, seen_urls)
        candidates.extend(direct_candidates)
        self._log(f"  Direct URLs total: {len(direct_candidates)} URLs")
        
        self._log(f"=== Multi-provider search complete: {len(candidates)} total URLs discovered ===")
        return candidates

    def _search_wikipedia(self, queries: List[str], seen_urls: Set[str]) -> List[Dict[str, Any]]:
        """Searches Wikipedia API for relevant articles. Free, no auth, no rate limits."""
        candidates = []
        for q in queries:
            try:
                # Wikipedia opensearch API
                params = {
                    "action": "opensearch",
                    "search": q,
                    "limit": 5,
                    "format": "json"
                }
                r = requests.get("https://en.wikipedia.org/w/api.php", params=params, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    titles = data[1] if len(data) > 1 else []
                    snippets = data[2] if len(data) > 2 else []
                    urls = data[3] if len(data) > 3 else []
                    
                    for i, url in enumerate(urls):
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            candidates.append({
                                "url": url,
                                "title": titles[i] if i < len(titles) else "Wikipedia",
                                "snippet": snippets[i] if i < len(snippets) else "",
                                "seed_query": q
                            })
                time.sleep(0.3)  # Be polite
            except Exception as e:
                self._log(f"    Wikipedia search error for '{q}': {e}")
        return candidates

    def _search_google_news(self, queries: List[str], seen_urls: Set[str]) -> List[Dict[str, Any]]:
        """Fetches Google News RSS feed results. Free, no API key needed."""
        candidates = []
        for q in queries[:6]:  # Limit to 6 queries to avoid spam
            try:
                encoded_q = urllib.parse.quote_plus(q)
                rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en-US&gl=US&ceid=US:en"
                r = requests.get(rss_url, headers=self.headers, timeout=10)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "lxml-xml")
                    items = soup.find_all("item")[:5]  # Top 5 per query
                    for item in items:
                        link_el = item.find("link")
                        title_el = item.find("title")
                        if link_el:
                            # Google News wraps URLs; extract the actual link text
                            url = link_el.get_text(strip=True) if link_el else ""
                            if not url.startswith("http"):
                                url = link_el.next_sibling
                                if not url or not str(url).startswith("http"):
                                    continue
                                url = str(url).strip()
                            if url and url not in seen_urls:
                                seen_urls.add(url)
                                candidates.append({
                                    "url": url,
                                    "title": title_el.get_text(strip=True) if title_el else "News",
                                    "snippet": "",
                                    "seed_query": q
                                })
                time.sleep(0.5)
            except Exception as e:
                self._log(f"    Google News error for '{q}': {e}")
        return candidates

    def _search_bing(self, queries: List[str], seen_urls: Set[str]) -> List[Dict[str, Any]]:
        """Scrapes Bing web search results. Very reliable, rarely rate-limits."""
        candidates = []
        for q in queries:
            try:
                encoded_q = urllib.parse.quote_plus(q)
                bing_url = f"https://www.bing.com/search?q={encoded_q}&count=10"
                r = requests.get(bing_url, headers={
                    **self.headers,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                }, timeout=10)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "lxml")
                    # Bing uses <li class="b_algo"> for organic results
                    for result in soup.select("li.b_algo"):
                        link = result.find("a", href=True)
                        if link:
                            url = link["href"]
                            title = link.get_text(strip=True)
                            # Get snippet
                            snippet_el = result.find("p") or result.find("div", class_="b_caption")
                            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                            if url.startswith("http") and url not in seen_urls:
                                seen_urls.add(url)
                                candidates.append({
                                    "url": url,
                                    "title": title or "Bing Result",
                                    "snippet": snippet,
                                    "seed_query": q
                                })
                time.sleep(1.0)
            except Exception as e:
                self._log(f"    Bing error for '{q}': {e}")
        return candidates

    def _search_google_scholar(self, queries: List[str], seen_urls: Set[str]) -> List[Dict[str, Any]]:
        """Scrapes Google Scholar for academic papers and citations."""
        candidates = []
        for q in queries[:6]:  # Limit queries to avoid blocks
            try:
                encoded_q = urllib.parse.quote_plus(q)
                scholar_url = f"https://scholar.google.com/scholar?q={encoded_q}&hl=en"
                r = requests.get(scholar_url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9"
                }, timeout=10)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "lxml")
                    for result in soup.select("div.gs_r.gs_or.gs_scl"):
                        # Title link
                        title_el = result.select_one("h3.gs_rt a")
                        if title_el and title_el.get("href"):
                            url = title_el["href"]
                            title = title_el.get_text(strip=True)
                            # Snippet
                            snippet_el = result.select_one("div.gs_rs")
                            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                            if url.startswith("http") and url not in seen_urls:
                                seen_urls.add(url)
                                candidates.append({
                                    "url": url,
                                    "title": f"[Scholar] {title}",
                                    "snippet": snippet,
                                    "seed_query": q
                                })
                        # Also grab PDF/cached links
                        for side_link in result.select("div.gs_or_ggsm a"):
                            href = side_link.get("href", "")
                            if href.startswith("http") and href not in seen_urls and href.endswith(".pdf"):
                                seen_urls.add(href)
                                candidates.append({
                                    "url": href,
                                    "title": f"[PDF] {title_el.get_text(strip=True) if title_el else 'Paper'}",
                                    "snippet": "",
                                    "seed_query": q
                                })
                time.sleep(2.0)  # Scholar is more aggressive with rate limiting
            except Exception as e:
                self._log(f"    Scholar error for '{q}': {e}")
        return candidates

    def _search_archive_org(self, queries: List[str], seen_urls: Set[str]) -> List[Dict[str, Any]]:
        """Searches Internet Archive for historical and archival documents."""
        candidates = []
        for q in queries[:6]:
            try:
                # Internet Archive search API (Scrub Search)
                params = {
                    "q": q,
                    "output": "json",
                    "rows": 5,
                    "page": 1,
                    "fl[]": ["identifier", "title", "description"],
                    "sort[]": "downloads desc"
                }
                r = requests.get("https://archive.org/advancedsearch.php", params=params, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    docs = data.get("response", {}).get("docs", [])
                    for doc in docs:
                        identifier = doc.get("identifier", "")
                        title = doc.get("title", "Archive Document")
                        desc = doc.get("description", "")
                        if isinstance(desc, list):
                            desc = desc[0] if desc else ""
                        url = f"https://archive.org/details/{identifier}"
                        if url not in seen_urls:
                            seen_urls.add(url)
                            candidates.append({
                                "url": url,
                                "title": f"[Archive] {title}",
                                "snippet": str(desc)[:200],
                                "seed_query": q
                            })
                time.sleep(0.5)
            except Exception as e:
                self._log(f"    Archive.org error for '{q}': {e}")
        return candidates

    def _construct_direct_urls(self, queries: List[str], seen_urls: Set[str]) -> List[Dict[str, Any]]:
        """Constructs search URLs for known high-trust domains directly."""
        candidates = []
        # High-trust domains with their search URL patterns
        domain_search_patterns = [
            ("https://www.un.org/en/search?query={q}", "UN Official"),
            ("https://www.cfr.org/search?keyword={q}", "CFR Think Tank"),
            ("https://www.brookings.edu/search/?s={q}", "Brookings Institution"),
            ("https://www.csis.org/search?search_api_fulltext={q}", "CSIS"),
            ("https://www.rand.org/search.html?query={q}", "RAND Corporation"),
            ("https://www.crisisgroup.org/search?query={q}", "Crisis Group"),
            ("https://www.sipri.org/search?query={q}", "SIPRI"),
            ("https://www.bbc.com/search?q={q}", "BBC News"),
            ("https://www.aljazeera.com/search/{q}", "Al Jazeera"),
            ("https://www.reuters.com/search/news?query={q}", "Reuters"),
        ]
        
        # Use top 3 most relevant queries for direct domain search
        top_queries = queries[:3]
        for q in top_queries:
            encoded_q = urllib.parse.quote_plus(q)
            for pattern, domain_label in domain_search_patterns:
                url = pattern.format(q=encoded_q)
                if url not in seen_urls:
                    seen_urls.add(url)
                    candidates.append({
                        "url": url,
                        "title": f"[{domain_label}] Search: {q[:40]}",
                        "snippet": f"Direct search on {domain_label}",
                        "seed_query": q
                    })
        return candidates

    def score_url(self, url: str) -> float:
        """Assigns a quality trust score (0.0 to 1.0) to a URL based on its domain."""
        try:
            parsed = urllib.parse.urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]

            # Heuristics
            # 1. Check exact matches or subdomains in high-trust list
            for ht_domain in HIGH_TRUST_DOMAINS:
                if domain == ht_domain or domain.endswith("." + ht_domain):
                    return 0.95

            # 2. Check general top level domains
            if domain.endswith(".gov"):
                return 1.0
            if domain.endswith(".edu"):
                return 0.90
            if domain.endswith(".int"):
                return 0.95
            # Wikipedia special case (encyclopedic, well-sourced)
            if "wikipedia.org" in domain:
                return 0.80

            if domain.endswith(".org"):
                # org are usually think tanks/NGOs, but could be personal blogs
                return 0.75

            # 3. Check major newspapers / media check (e.g. nytimes, guardian, bloomberg, economist)
            media_keywords = ["nytimes", "theguardian", "bloomberg", "economist", "ft.com", "wsj", "bbc", "aljazeera", "dw.com"]
            for keyword in media_keywords:
                if keyword in domain:
                    return 0.85

            # Default commercial / blog
            return 0.50
        except Exception:
            return 0.50

    def clean_html(self, html_content: str, source_url: str = "") -> Tuple[str, str, Set[str]]:
        """Parses HTML, cleans text, extracts title, and finds outbound links.
        Has a Wikipedia-specific code path for cleaner extraction."""
        soup = BeautifulSoup(html_content, "lxml")
        is_wikipedia = "wikipedia.org" in source_url
        
        # Extract title
        title = "Untitled"
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
            # Clean Wikipedia title suffix
            if is_wikipedia and " - Wikipedia" in title:
                title = title.replace(" - Wikipedia", "")

        # Remove boilerplates / noise elements
        for element in soup(["script", "style", "nav", "header", "footer", "aside", "form", "iframe"]):
            element.decompose()

        # Wikipedia-specific noise removal
        if is_wikipedia:
            # Remove edit links, navboxes, infobox captions, reference numbers, sidebar etc.
            for selector in ["sup.reference", ".mw-editsection", ".navbox", ".sidebar",
                             ".sistersitebox", ".metadata", ".noprint", ".mw-empty-elt",
                             ".shortdescription", ".geo-nondefault", ".geo-multi-punct",
                             "#toc", ".toc", ".catlinks", ".mw-indicators"]:
                for el in soup.select(selector):
                    el.decompose()

        # Extract clean text paragraphs
        paragraphs = []
        for p in soup.find_all(["p", "h1", "h2", "h3", "h4", "article"]):
            text = p.get_text().strip()
            if text and len(text) > 40:  # Ignore tiny snippets/buttons
                paragraphs.append(text)
        
        raw_text = "\n\n".join(paragraphs)

        # Extract outbound links
        outbound_links = set()
        for link in soup.find_all("a", href=True):
            href = link["href"]
            # Convert relative to absolute URL
            if source_url:
                absolute_url = urllib.parse.urljoin(source_url, href)
            else:
                absolute_url = urllib.parse.urljoin(href, href)
            parsed = urllib.parse.urlparse(absolute_url)
            
            # Keep only HTTP/HTTPS
            if parsed.scheme in ["http", "https"]:
                # Clean query strings/hash parameters
                cleaned_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                domain = parsed.netloc.lower()
                
                # Filter out excluded social media domains
                is_excluded = False
                for d in EXCLUDED_DOMAINS:
                    if d in domain:
                        is_excluded = True
                        break
                
                if not is_excluded:
                    outbound_links.add(cleaned_url)

        return title, raw_text, outbound_links

    def _extract_wikipedia_links(self, html_content: str, source_url: str) -> Tuple[Set[str], Set[str]]:
        """
        Wikipedia-specific link extraction. Returns two sets:
        1. internal_wiki_links: Links to other Wikipedia articles (for deep knowledge mining)
        2. reference_urls: External citation URLs from the References section (primary sources)
        """
        soup = BeautifulSoup(html_content, "lxml")
        internal_wiki_links = set()
        reference_urls = set()
        
        # --- 1. Internal Wikipedia article links ---
        # These are in the article body, linking to /wiki/Article_Name
        body_content = soup.find("div", {"id": "bodyContent"}) or soup.find("div", {"class": "mw-parser-output"}) or soup
        for link in body_content.find_all("a", href=True):
            href = link["href"]
            # Match internal wiki article links: /wiki/Article_Name
            # Exclude special pages, files, categories, etc.
            if href.startswith("/wiki/") and not any(prefix in href for prefix in [
                "/wiki/Special:", "/wiki/File:", "/wiki/Category:",
                "/wiki/Template:", "/wiki/Help:", "/wiki/Portal:",
                "/wiki/Talk:", "/wiki/User:", "/wiki/Wikipedia:",
                "/wiki/Main_Page"
            ]):
                full_url = f"https://en.wikipedia.org{href.split('#')[0]}"  # Strip anchors
                internal_wiki_links.add(full_url)
        
        # --- 2. External reference/citation URLs ---
        # These are in <cite> tags, .references section, and .external links
        
        # Method A: Find all <cite> tags (Wikipedia's reference format)
        for cite in soup.find_all("cite"):
            for link in cite.find_all("a", href=True):
                href = link["href"]
                if href.startswith("http") and "wikipedia.org" not in href:
                    # Clean the URL
                    parsed = urllib.parse.urlparse(href)
                    cleaned = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    # Filter excluded domains
                    domain = parsed.netloc.lower()
                    if not any(d in domain for d in EXCLUDED_DOMAINS):
                        reference_urls.add(cleaned)
        
        # Method B: Find links marked as "external text" in reference lists
        ref_sections = soup.find_all("ol", {"class": "references"})
        for ref_list in ref_sections:
            for link in ref_list.find_all("a", {"class": "external"}, href=True):
                href = link["href"]
                if href.startswith("http") and "wikipedia.org" not in href:
                    parsed = urllib.parse.urlparse(href)
                    cleaned = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                    domain = parsed.netloc.lower()
                    if not any(d in domain for d in EXCLUDED_DOMAINS):
                        reference_urls.add(cleaned)
        
        # Method C: "External links" section at the bottom
        ext_links_header = soup.find("span", {"id": "External_links"})
        if ext_links_header:
            ext_section = ext_links_header.find_parent()
            if ext_section:
                next_el = ext_section.find_next_sibling()
                while next_el and next_el.name in ["ul", "ol", "div"]:
                    for link in next_el.find_all("a", href=True):
                        href = link["href"]
                        if href.startswith("http") and "wikipedia.org" not in href:
                            parsed = urllib.parse.urlparse(href)
                            cleaned = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                            domain = parsed.netloc.lower()
                            if not any(d in domain for d in EXCLUDED_DOMAINS):
                                reference_urls.add(cleaned)
                    next_el = next_el.find_next_sibling()
        
        self._log(f"  Wikipedia deep extract: {len(internal_wiki_links)} internal links, {len(reference_urls)} reference citations")
        return internal_wiki_links, reference_urls

    def fetch_url(self, url: str) -> Optional[str]:
        """Fetches page content via requests (fast) with a Playwright fallback (for JS pages)."""
        self._log(f"Fetching: {url}")
        
        # 1. Skip Playwright if URL is a PDF
        is_pdf = url.lower().endswith('.pdf') or '.pdf?' in url.lower()
        
        # 2. Attempt requests (Fast HTTP call)
        try:
            response = requests.get(url, headers=self.headers, timeout=8)
            if response.status_code == 200:
                if len(response.text) > 1000 and "javascript" not in response.text.lower()[:200]:
                    self._log(f"  Successfully fetched via requests ({len(response.text)} bytes)")
                    return response.text
                if is_pdf:
                    self._log("  Requests returned minimal content for PDF, skipping Playwright fallback.")
                    return None
                self._log("  Requests returned minimal content, falling back to Playwright...")
            else:
                if is_pdf:
                    self._log(f"  Requests failed for PDF (status: {response.status_code}), skipping Playwright.")
                    return None
                self._log(f"  Requests failed with status code: {response.status_code}. Falling back to Playwright...")
        except Exception as e:
            if is_pdf:
                self._log(f"  Requests failed for PDF ({e}), skipping Playwright.")
                return None
            self._log(f"  Requests failed with error: {e}. Falling back to Playwright...")

        # 3. Playwright Fallback (Renders JavaScript and resolves client-side blocks)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent=self.headers["User-Agent"])
                page = context.new_page()
                
                # Navigate with a shorter timeout (8 seconds)
                page.goto(url, wait_until="domcontentloaded", timeout=8000)
                # Wait briefly (1 second)
                page.wait_for_timeout(1000)
                
                html_content = page.content()
                browser.close()
                self._log(f"  Successfully fetched via Playwright ({len(html_content)} bytes)")
                return html_content
        except Exception as pe:
            self._log(f"  Playwright fallback failed for {url}: {pe}")
            return None


    def _classify_category(self, query_lower: str) -> str:
        """Classifies a seed query into a domain category."""
        if any(k in query_lower for k in ["quantum", "ai", "intelligence", "neural", "learning", "gene", "crispr", "editing", "genetics", "energy", "fusion", "science", "physics"]):
            return "Science"
        elif any(k in query_lower for k in ["rome", "roman", "caesar", "history", "historical", "battle", "revolution", "monarch", "empire"]):
            return "History"
        elif any(k in query_lower for k in ["market", "finance", "investment", "company", "corporation", "startup", "business", "economics", "equity"]):
            return "Business"
        elif any(k in query_lower for k in ["court", "legal", "judge", "policy", "regulation", "law", "statute", "constitution"]):
            return "Law"
        elif "cyber" in query_lower:
            return "Cyber Warfare"
        elif "sea" in query_lower or "maritime" in query_lower:
            return "Maritime Security"
        elif "semiconductor" in query_lower:
            return "Supply Chain"
        elif "border" in query_lower:
            return "Territorial Disputes"
        return "Geopolitics"

    def crawl_pipeline(self, seed_queries: List[str], db_conn_func: Callable[[], Any], 
                       max_pages: int = 50, max_depth: int = 1) -> Dict[str, Any]:
        """
        Full automated discovery crawl with deep Wikipedia mining:
        1. Multi-provider search (DDG + Wikipedia API + Google News RSS)
        2. Crawl seed URLs, clean, score, chunk, and store.
        3. For Wikipedia pages: extract internal wiki links (depth +2 allowance)
           AND external reference/citation URLs (always followed as primary sources).
        4. For non-Wikipedia pages: follow high-trust outbound links (depth +1).
        """
        WIKI_DEPTH_BONUS = 2  # Wikipedia internal links get extra depth allowance
        
        crawled_urls = set()
        crawling_queue: List[Tuple[str, int, float, str]] = []  # (url, depth, trust, category)
        
        # Prepopulate queue with multi-provider search
        candidates = self.search_queries(seed_queries, max_results=8)
        for cand in candidates:
            url = cand["url"]
            trust_score = self.score_url(url)
            category = self._classify_category(cand["seed_query"].lower())
            crawling_queue.append((url, 0, trust_score, category))

        self._log(f"Initial discovery queue: {len(crawling_queue)} URLs from multi-provider search.")

        db = db_conn_func()
        pages_indexed = 0

        # Sort queue: prioritize high trust URLs
        crawling_queue.sort(key=lambda x: x[2], reverse=True)

        while crawling_queue and pages_indexed < max_pages:
            url, depth, trust_score, category = crawling_queue.pop(0)

            if url in crawled_urls:
                continue
            crawled_urls.add(url)

            is_wikipedia = "wikipedia.org" in url
            self._log(f"Crawl [{pages_indexed}/{max_pages}] (depth={depth}) {'[WIKI]' if is_wikipedia else ''} {url[:80]}...")
            
            html = self.fetch_url(url)
            if not html:
                continue

            # Process HTML
            try:
                title, raw_text, outbound_links = self.clean_html(html, source_url=url)
                
                # Basic validation: ensure text content is substantial
                if len(raw_text.strip()) < 300:
                    self._log(f"  Skipping: insufficient content ({len(raw_text)} chars).")
                    continue

                # Store source in SQLite
                source_id = db.insert_source(
                    url=url,
                    title=title,
                    trust_score=trust_score,
                    raw_content=raw_text,
                    category=category
                )
                
                # Split text into semantic chunks
                chunks = self.chunk_text(raw_text, chunk_size=1000, overlap=200)
                
                # Save chunks with dummy embeddings (will be embedded properly later)
                import numpy as np
                dummy_embeddings = [np.array([], dtype=np.float32) for _ in chunks]
                db.insert_chunks_and_embeddings(source_id, chunks, dummy_embeddings)
                
                self._log(f"  Indexed ID {source_id}: '{title[:50]}' ({len(chunks)} chunks, Trust: {trust_score:.2f})")
                pages_indexed += 1

                # ── Wikipedia Deep Mining ──
                if is_wikipedia:
                    wiki_links, ref_urls = self._extract_wikipedia_links(html, url)
                    
                    # A) Internal wiki links → follow with depth bonus
                    wiki_max_depth = max_depth + WIKI_DEPTH_BONUS
                    if depth < wiki_max_depth:
                        added_wiki = 0
                        for wlink in wiki_links:
                            if wlink not in crawled_urls and added_wiki < 15:  # Cap at 15 per article
                                crawling_queue.append((wlink, depth + 1, 0.80, category))
                                added_wiki += 1
                        self._log(f"  Wiki internal: queued {added_wiki} article links (max_depth={wiki_max_depth})")
                    
                    # B) External reference/citation URLs → ALWAYS follow (these are primary sources)
                    added_refs = 0
                    for ref_url in ref_urls:
                        if ref_url not in crawled_urls and added_refs < 10:  # Cap at 10 per article
                            ref_trust = self.score_url(ref_url)
                            if ref_trust >= 0.50:  # Lower threshold — these are cited sources
                                crawling_queue.append((ref_url, depth + 1, ref_trust, category))
                                added_refs += 1
                    self._log(f"  Wiki references: queued {added_refs} citation source URLs")
                
                # ── Standard outbound link expansion ──
                elif depth < max_depth:
                    added_out = 0
                    for link in outbound_links:
                        if link not in crawled_urls:
                            link_trust = self.score_url(link)
                            if link_trust >= 0.70:
                                crawling_queue.append((link, depth + 1, link_trust, category))
                                added_out += 1
                    if added_out > 0:
                        self._log(f"  Outbound: queued {added_out} high-trust links")
                
                # Re-sort queue by trust score
                crawling_queue.sort(key=lambda x: x[2], reverse=True)

            except Exception as ex:
                self._log(f"  Error processing {url}: {ex}")
            
            # Polite delay (shorter for Wikipedia since they're lenient)
            time.sleep(0.5 if is_wikipedia else 1.5)

        self._log(f"Crawl completed! Total pages indexed: {pages_indexed}, URLs attempted: {len(crawled_urls)}")
        return {"pages_indexed": pages_indexed, "total_attempted": len(crawled_urls)}

    def chunk_text(self, text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        """Chunks clean text into sliding semantic window pieces."""
        # Simple window-based paragraph splitter
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = []
        current_len = 0

        for p in paragraphs:
            p_len = len(p)
            # If paragraph itself is huge, split it by sentences
            if p_len > chunk_size:
                sentences = re.split(r"(?<=[.!?])\s+", p)
                for s in sentences:
                    if current_len + len(s) > chunk_size and current_chunk:
                        chunks.append(" ".join(current_chunk))
                        # Retain some sentences for overlap
                        overlap_sentences = []
                        overlap_len = 0
                        for os in reversed(current_chunk):
                            if overlap_len + len(os) < overlap:
                                overlap_sentences.insert(0, os)
                                overlap_len += len(os)
                            else:
                                break
                        current_chunk = overlap_sentences
                        current_len = overlap_len
                    current_chunk.append(s)
                    current_len += len(s)
            else:
                if current_len + p_len > chunk_size and current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    # Basic overlap setup
                    current_chunk = [current_chunk[-1]] if len(current_chunk) > 1 else []
                    current_len = sum(len(x) for x in current_chunk)
                current_chunk.append(p)
                current_len += p_len

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        # Filter out tiny chunks
        return [c for c in chunks if len(c.strip()) > 150]

    def generate_seeds_for_topic(self, committee: str, agenda: str) -> List[str]:
        """Produces 10-15 diverse seed queries using string templates."""
        comm = re.sub(r'\s+', ' ', committee).strip()
        agen = re.sub(r'\s+', ' ', agenda).strip()
        
        seeds = [
            f"{comm} {agen}",
            f"{agen} background analysis",
            f"{agen} history timeline",
            f"{agen} international law sovereignty",
            f"{agen} key stakeholders positions",
            f"{comm} official resolutions",
            f"{comm} mandate guidelines",
            f"{agen} bilateral agreements disputes",
            f"{agen} strategic security implications",
            f"{agen} legal precedents rulings",
            f"{agen} treaty frameworks",
            f"geopolitical impact of {agen}"
        ]
        seen = set()
        return [s for s in seeds if s and not (s in seen or seen.add(s))][:12]

