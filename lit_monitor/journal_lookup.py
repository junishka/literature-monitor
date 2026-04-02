"""Search OpenAlex for journals/sources by research field or name."""

import logging

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openalex.org/sources"


def search_journals(query: str, mailto: str = "", max_results: int = 20) -> list[dict]:
    """Search for academic journals by name or field.

    Returns list of dicts with: id, name, publisher, works_count, h_index, type
    """
    params = {
        "search": query,
        "per_page": max_results,
        "sort": "works_count:desc",
    }
    if mailto:
        params["mailto"] = mailto

    try:
        resp = requests.get(BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"OpenAlex sources API error: {e}")
        return []

    journals = []
    for source in data.get("results", []):
        source_type = source.get("type", "")
        # Only include journals and conferences
        if source_type not in ("journal", "conference"):
            continue

        openalex_id = source.get("id", "")
        # Extract short ID (e.g., "S117778295" from "https://openalex.org/S117778295")
        short_id = openalex_id.split("/")[-1] if openalex_id else ""

        journals.append({
            "id": short_id,
            "full_id": openalex_id,
            "name": source.get("display_name", ""),
            "publisher": source.get("host_organization_name", "") or "",
            "works_count": source.get("works_count", 0),
            "h_index": source.get("summary_stats", {}).get("h_index", 0),
            "type": source_type,
            "issn": source.get("issn_l", ""),
        })

    return journals


def get_top_journals_for_field(field: str, mailto: str = "") -> list[dict]:
    """Get top journals for a research field using OpenAlex concepts/topics.

    This searches for journals whose papers frequently use the given concept.
    """
    # First, find the concept
    try:
        resp = requests.get(
            "https://api.openalex.org/topics",
            params={"search": field, "per_page": 1, "mailto": mailto},
            timeout=15,
        )
        resp.raise_for_status()
        topics = resp.json().get("results", [])
    except requests.RequestException:
        # Fall back to direct journal search
        return search_journals(field, mailto)

    if not topics:
        return search_journals(field, mailto)

    topic_id = topics[0].get("id", "")

    # Get sources that publish the most papers in this topic
    try:
        resp = requests.get(
            "https://api.openalex.org/sources",
            params={
                "filter": f"topics.id:{topic_id}",
                "sort": "works_count:desc",
                "per_page": 20,
                "mailto": mailto,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return search_journals(field, mailto)

    journals = []
    for source in data.get("results", []):
        if source.get("type") not in ("journal", "conference"):
            continue

        openalex_id = source.get("id", "")
        short_id = openalex_id.split("/")[-1] if openalex_id else ""

        journals.append({
            "id": short_id,
            "full_id": openalex_id,
            "name": source.get("display_name", ""),
            "publisher": source.get("host_organization_name", "") or "",
            "works_count": source.get("works_count", 0),
            "h_index": source.get("summary_stats", {}).get("h_index", 0),
            "type": source.get("type", ""),
            "issn": source.get("issn_l", ""),
        })

    return journals
