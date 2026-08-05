"""Resolve a user's input to PDF bytes plus whatever metadata came free.

Order of preference, per docs/DESIGN.md: arXiv is the dominant case and its API
gives title/authors/abstract/date for nothing, so the common path costs no LLM
call at all. DOIs resolve via Crossref for metadata and OpenAlex for an
open-access PDF link. A direct PDF URL is fetched as-is.

Publishers behind Cloudflare or a paywall will refuse automated fetching. That
is expected, not exceptional: it raises `FetchError` and the caller turns it into
"upload it yourself".
"""
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree

import httpx

_ARXIV_API = "http://export.arxiv.org/api/query"
_CROSSREF_API = "https://api.crossref.org/works"
_OPENALEX_API = "https://api.openalex.org/works"
_ATOM = {"atom": "http://www.w3.org/2005/Atom"}

# Be a good citizen with these APIs; arXiv asks for identifiable traffic.
_HEADERS = {"User-Agent": "paper-reader/0.1 (local research tool)"}
_TIMEOUT = 60.0

# 2401.12345, optionally versioned; or the pre-2007 style, math/0309136.
_ARXIV_NEW = r"\d{4}\.\d{4,5}(?:v\d+)?"
_ARXIV_OLD = r"[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?"
_ARXIV_ID_RE = re.compile(rf"^(?:{_ARXIV_NEW}|{_ARXIV_OLD})$")
_ARXIV_URL_RE = re.compile(rf"arxiv\.org/(?:abs|pdf)/({_ARXIV_NEW}|{_ARXIV_OLD})")
_DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)")


class FetchError(RuntimeError):
    """Could not retrieve a PDF. The message is shown to the user."""


@dataclass
class FetchResult:
    pdf_bytes: bytes
    filename: str
    source_url: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None


def _get(client: httpx.Client, url: str) -> httpx.Response:
    try:
        r = client.get(url, follow_redirects=True)
        r.raise_for_status()
        return r
    except httpx.HTTPStatusError as e:
        raise FetchError(
            f"Source returned {e.response.status_code}. If this is paywalled or "
            "behind a bot check, download the PDF and upload it instead."
        ) from e
    except httpx.HTTPError as e:
        raise FetchError(f"Could not reach {url}: {e}") from e


def _download_pdf(client: httpx.Client, url: str) -> bytes:
    r = _get(client, url)
    # Cloudflare and paywall interstitials answer 200 with HTML, so trust the
    # magic bytes rather than the status code or the content-type header.
    if not r.content.startswith(b"%PDF"):
        raise FetchError(
            "That URL did not return a PDF (likely a login or bot-check page). "
            "Download it and upload the file instead."
        )
    return r.content


def _identify(source: str) -> tuple[str, str]:
    """Classify raw user input as ('arxiv'|'doi'|'url', identifier)."""
    s = source.strip()
    if _ARXIV_ID_RE.match(s):
        return "arxiv", s
    if m := _ARXIV_URL_RE.search(s):
        return "arxiv", m.group(1)
    if s.lower().startswith("doi:"):
        return "doi", s[4:].strip()
    if "doi.org/" in s and (m := _DOI_RE.search(s)):
        return "doi", m.group(1)
    if _DOI_RE.fullmatch(s):
        return "doi", s
    if s.startswith(("http://", "https://")):
        return "url", s
    raise FetchError(f"Could not recognise {source!r} as an arXiv ID, DOI, or URL.")


def _fetch_arxiv(client: httpx.Client, arxiv_id: str) -> FetchResult:
    r = _get(client, f"{_ARXIV_API}?id_list={arxiv_id}&max_results=1")
    entry = ElementTree.fromstring(r.text).find("atom:entry", _ATOM)
    if entry is None:
        raise FetchError(f"arXiv has no record for {arxiv_id}.")

    def text(tag: str) -> str | None:
        el = entry.find(f"atom:{tag}", _ATOM)
        return " ".join(el.text.split()) if el is not None and el.text else None

    published = text("published")
    pdf_bytes = _download_pdf(client, f"https://arxiv.org/pdf/{arxiv_id}")

    return FetchResult(
        pdf_bytes=pdf_bytes,
        filename=f"{arxiv_id.replace('/', '_')}.pdf",
        source_url=f"https://arxiv.org/abs/{arxiv_id}",
        arxiv_id=arxiv_id,
        title=text("title"),
        authors=[
            " ".join(a.text.split())
            for a in entry.findall("atom:author/atom:name", _ATOM)
            if a.text
        ],
        year=int(published[:4]) if published else None,
        abstract=text("summary"),
    )


def _fetch_doi(client: httpx.Client, doi: str) -> FetchResult:
    meta: dict = {}
    try:
        meta = _get(client, f"{_CROSSREF_API}/{doi}").json().get("message", {})
    except FetchError:
        pass  # Metadata is a bonus; without it we can still serve the PDF.

    # OpenAlex knows where the open-access copy lives, which Crossref does not.
    pdf_url = None
    try:
        loc = _get(client, f"{_OPENALEX_API}/doi:{doi}").json().get("best_oa_location")
        pdf_url = (loc or {}).get("pdf_url")
    except FetchError:
        pass
    if not pdf_url:
        raise FetchError(
            f"No open-access PDF found for {doi}. Download it and upload the file instead."
        )

    title = (meta.get("title") or [None])[0]
    container = (meta.get("container-title") or [None])[0]
    date_parts = (meta.get("issued") or {}).get("date-parts") or [[None]]

    return FetchResult(
        pdf_bytes=_download_pdf(client, pdf_url),
        filename=f"{doi.replace('/', '_')}.pdf",
        source_url=f"https://doi.org/{doi}",
        doi=doi,
        title=" ".join(title.split()) if title else None,
        authors=[
            " ".join(f"{a.get('given', '')} {a.get('family', '')}".split())
            for a in meta.get("author", [])
        ],
        year=date_parts[0][0],
        venue=container,
        abstract=meta.get("abstract"),
    )


def _fetch_url(client: httpx.Client, url: str) -> FetchResult:
    filename = url.rstrip("/").rsplit("/", 1)[-1] or "paper"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    return FetchResult(
        pdf_bytes=_download_pdf(client, url),
        filename=filename,
        source_url=url,
    )


def fetch(source: str) -> FetchResult:
    """Resolve an arXiv ID/URL, DOI, or direct PDF URL to bytes + metadata."""
    kind, ident = _identify(source)
    with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
        if kind == "arxiv":
            return _fetch_arxiv(client, ident)
        if kind == "doi":
            return _fetch_doi(client, ident)
        return _fetch_url(client, ident)


def from_upload(filename: str, data: bytes) -> FetchResult:
    """The fallback path: a file the user already had. No metadata comes free."""
    if not data.startswith(b"%PDF"):
        raise FetchError("That file is not a PDF.")
    return FetchResult(pdf_bytes=data, filename=filename or "upload.pdf")
