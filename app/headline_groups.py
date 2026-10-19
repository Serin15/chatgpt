"""Conservative display grouping; raw news and contract evidence stay separate."""

import re
import unicodedata

from app.models import epoch


def headline_key(item):
    title = unicodedata.normalize("NFKC", item["title"])
    publisher = item.get("publisher_reported") or item.get("publisher") or ""
    if publisher:
        title = re.sub(r"\s+[-–—|]\s*" + re.escape(publisher) + r"\s*$", "", title, flags=re.I)
    title = re.sub(r"[^\w]+", " ", title.casefold()).strip()
    return title if len(title) >= 24 and len(title.split()) >= 4 else None


def group_headlines(items):
    groups = []
    for item in items:
        key = headline_key(item)
        try:
            published = epoch(item["published_at"])
        except (ValueError, TypeError, KeyError, OverflowError):
            published = None
        group = next(
            (
                g
                for g in groups
                if key
                and g["key"] == key
                and published is not None
                and g["published"] is not None
                and abs(published - g["published"]) <= 21600
                and not item.get("contracts")
                and not g["representative"].get("contracts")
            ),
            None,
        )
        if group is None:
            groups.append(
                {"key": key, "published": published, "representative": item, "members": [item]}
            )
        else:
            group["members"].append(item)
            if quality(item) > quality(group["representative"]):
                group["representative"] = item
    result = []
    for group in groups:
        related = [
            {
                k: member.get(k)
                for k in [
                    "news_id",
                    "url",
                    "title",
                    "publisher_reported",
                    "published_at",
                    "first_seen_at",
                    "document_state",
                ]
            }
            for member in group["members"]
        ]
        result.append(
            group["representative"]
            | {
                "related_reports": related,
                "headline_group_only": True,
                "grouping_note": "Same normalized headline within six hours; not proof of shared facts or independent reporting. Contract-bearing documents are never merged.",
            }
        )
    return result


def quality(item):
    return (item.get("document_state") == "read", item.get("source_kind") != "headline_only")
