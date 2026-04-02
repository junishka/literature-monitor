"""Query the OpenAlex API for recent papers. Free, no authentication required."""

import logging
from datetime import date

import requests

from .scopus_client import Paper

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openalex.org/works"

# Polite pool: include an email for faster rate limits (optional)
MAILTO = ""


def search_openalex(
    keywords: list[str],
    since_date: date,
    source_ids: list[str] | None = None,
    max_results: int = 50,
    mailto: str = "",
) -> list[Paper]:
    """Search OpenAlex for papers matching keywords published since a date.

    Runs one query per keyword (OpenAlex search doesn't support OR),
    then deduplicates by DOI/title.
    """
    # Build source filter (journals)
    filters_base = [f"from_publication_date:{since_date.isoformat()}"]

    if source_ids:
        source_filter = "|".join(
            f"https://openalex.org/{sid}" if not sid.startswith("http") else sid
            for sid in source_ids
        )
        filters_base.append(f"primary_location.source.id:{source_filter}")

    filter_str = ",".join(filters_base)

    # Search each keyword in title + abstract only (not full text)
    seen_ids = set()
    papers = []

    for keyword in keywords:
        if len(papers) >= max_results:
            break

        # Use title.search and abstract.search filters for precision
        # instead of the broad "search" parameter
        for field in ["title.search", "abstract.search"]:
            keyword_filter = f"{filter_str},{field}:{keyword}"

            params = {
                "filter": keyword_filter,
                "sort": "publication_date:desc",
                "per_page": min(max_results, 50),
                "mailto": mailto or MAILTO,
                "page": 1,
            }

            try:
                resp = requests.get(BASE_URL, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                logger.error(f"OpenAlex API error for '{keyword}' ({field}): {e}")
                continue

            for work in data.get("results", []):
                work_id = work.get("id", "")
                if work_id in seen_ids:
                    continue
                seen_ids.add(work_id)

                paper = _parse_work(work)
                papers.append(paper)

            count = data.get("meta", {}).get("count", 0)
            if count > 0:
                logger.info(f"  Keyword '{keyword}' ({field}): {count} matches")

    logger.info(f"OpenAlex: found {len(papers)} unique papers across {len(keywords)} keywords")
    return papers[:max_results]


def _parse_work(work: dict) -> Paper:
    """Parse an OpenAlex work object into a Paper."""
    authorships = work.get("authorships", [])
    authors = "; ".join(
        a.get("author", {}).get("display_name", "")
        for a in authorships[:5]
    )
    if len(authorships) > 5:
        authors += f" et al. ({len(authorships)} authors)"

    primary_loc = work.get("primary_location", {}) or {}
    source = primary_loc.get("source", {}) or {}
    journal = source.get("display_name", "Unknown")

    doi_url = work.get("doi", "") or ""
    doi = doi_url.replace("https://doi.org/", "")

    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
    pub_date = work.get("publication_date", "")
    url = doi_url or work.get("id", "")

    # Clean HTML tags from title (OpenAlex sometimes includes <scp> tags)
    import re
    title = re.sub(r"<[^>]+>", "", work.get("title", "No title") or "No title")

    return Paper(
        title=title,
        authors=authors,
        journal=journal,
        date=pub_date,
        doi=doi,
        abstract=abstract,
        source="openalex",
        url=url,
    )


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """Reconstruct abstract text from OpenAlex's inverted index format."""
    if not inverted_index:
        return ""

    # Build word list: {word: [positions]} → ordered text
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))

    word_positions.sort()
    return " ".join(word for _, word in word_positions)
