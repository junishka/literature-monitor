"""Query the Scopus Search API for recent papers."""

import logging
from dataclasses import dataclass
from datetime import date

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elsevier.com/content/search/scopus"


@dataclass
class Paper:
    title: str
    authors: str
    journal: str
    date: str
    doi: str
    abstract: str
    source: str  # "scopus" or "wos"
    url: str


def search_scopus(
    api_key: str,
    keywords: list[str],
    since_date: date,
    journal_issns: list[str] | None = None,
    max_results: int = 50,
) -> list[Paper]:
    """Search Scopus for papers matching keywords published since a given date."""
    if not api_key:
        logger.warning("No Scopus API key provided, skipping Scopus search")
        return []

    # Build the query
    keyword_query = " OR ".join(f'TITLE-ABS-KEY("{kw}")' for kw in keywords)
    date_query = f"PUBYEAR > {since_date.year - 1}"

    if journal_issns:
        issn_query = " OR ".join(f'ISSN({issn.replace("-", "")})' for issn in journal_issns)
        query = f"({keyword_query}) AND ({issn_query}) AND {date_query}"
    else:
        query = f"({keyword_query}) AND {date_query}"

    # Add date filter for more precision
    date_filter = f"PUBDATETXT(after {since_date.strftime('%B %d %Y')})"
    query = f"{query} AND {date_filter}"

    headers = {
        "X-ELS-APIKey": api_key,
        "Accept": "application/json",
    }

    params = {
        "query": query,
        "count": min(max_results, 25),
        "sort": "-coverDate",
        "field": "dc:title,dc:creator,prism:publicationName,prism:coverDate,prism:doi,dc:description,prism:url",
    }

    papers = []
    start = 0

    while start < max_results:
        params["start"] = start
        try:
            resp = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f"Scopus API error: {e}")
            break

        results = data.get("search-results", {})
        entries = results.get("entry", [])

        if not entries or (len(entries) == 1 and "error" in entries[0]):
            break

        for entry in entries:
            doi = entry.get("prism:doi", "")
            papers.append(Paper(
                title=entry.get("dc:title", "No title"),
                authors=entry.get("dc:creator", "Unknown"),
                journal=entry.get("prism:publicationName", "Unknown"),
                date=entry.get("prism:coverDate", ""),
                doi=doi,
                abstract=entry.get("dc:description", ""),
                source="scopus",
                url=f"https://doi.org/{doi}" if doi else entry.get("prism:url", ""),
            ))

        total = int(results.get("opensearch:totalResults", 0))
        start += len(entries)
        if start >= total:
            break

    logger.info(f"Scopus: found {len(papers)} papers")
    return papers
