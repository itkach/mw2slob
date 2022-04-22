import json
import urllib.request
from dataclasses import dataclass
from dataclasses import field
from typing import Iterable
from typing import Mapping
from typing import Set
from urllib.parse import urlencode


def get(mw_site, api_path="/w/api.php"):
    params = {
        "action": "query",
        "meta": "siteinfo",
        "siprop": "general|namespaces|interwikimap|rightsinfo",
        "format": "json",
    }
    query_string = urlencode(params)
    url = f"{mw_site}/{api_path}?{query_string}"
    with urllib.request.urlopen(url) as response:
        data = json.load(response)
        return data["query"]


def add_http(url):
    """
    >>> add_http("http://example.org")
    'http://example.org'
    >>> add_http("//example.org")
    'http://example.org'
    >>> add_http("example.org")
    'example.org'

    """
    return f"http:{url}" if url.startswith("//") else url


@dataclass(frozen=True)
class Info:
    sitename: str
    sitelang: str
    rtl: bool
    license_name: str
    license_url: str
    articlepath: str
    server: str
    interwikimap: Iterable[Mapping[str, str]] = ()
    namespaces: Mapping[str, dict] = field(default_factory=dict)


def info(siteinfo: Mapping, local_namespaces: Iterable[str] = ()) -> Info:
    local_namespaces = set(local_namespaces or ())
    valid_local_namespaces: Set[int] = set()
    for ns in siteinfo.get("namespaces", {}).values():
        ns_name = ns.get("*")
        ns_canonical_name = ns.get("canonical")
        ns_id = ns.get("id")
        ns_id_str = str(ns_id)
        for item in (ns_name, ns_canonical_name, ns_id_str):
            if item in local_namespaces:
                local_namespaces.remove(item)
                valid_local_namespaces.add(ns_id)
                break
    if local_namespaces:
        raise Exception(f"Invalid namespaces: {local_namespaces}")

    namespaces = {
        ns.get("id"): ns
        for ns in siteinfo.get("namespaces", {}).values()
        if ns.get("id") not in valid_local_namespaces
    }

    general_siteinfo = siteinfo["general"]
    sitename = general_siteinfo["sitename"]
    sitelang = general_siteinfo["lang"]
    rightsinfo = siteinfo["rightsinfo"]
    license_name = rightsinfo["text"]
    license_url = add_http(rightsinfo["url"])

    rtl = "rtl" in general_siteinfo
    articlepath = general_siteinfo.get("articlepath")
    if articlepath:
        articlepath = articlepath.split("$1", 1)[0]
    server = add_http(general_siteinfo.get("server", ""))
    interwikimap = siteinfo.get("interwikimap", [])
    return Info(
        sitename=sitename,
        sitelang=sitelang,
        rtl=rtl,
        license_name=license_name,
        license_url=license_url,
        articlepath=articlepath,
        server=server,
        interwikimap=interwikimap,
        namespaces=namespaces,
    )
