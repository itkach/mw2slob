import functools
import itertools
import logging
import os
from urllib.parse import urlparse

import couchdb

from . import convert
from . import siteinfo as si

log = logging.getLogger(__name__)


def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    args = [iter(iterable)] * n
    return itertools.zip_longest(fillvalue=fillvalue, *args)


def mkcouch(couch_url) -> tuple[couchdb.Database, couchdb.Database]:
    parsed_url = urlparse(couch_url)
    couch_db = parsed_url.path.lstrip("/")
    server_url = parsed_url.scheme + "://" + parsed_url.netloc
    server = couchdb.Server(server_url)
    return server[couch_db], server["siteinfo"]


def articles(args, info: si.Info):

    couch, _ = mkcouch(args.couch_url)

    startkey = args.startkey
    endkey = args.endkey
    key = args.key
    key_file = args.key_file
    langlinks = args.langlinks

    basic_view_args = {"stale": "ok", "include_docs": True}
    view_args = dict(basic_view_args)
    if startkey:
        view_args["startkey"] = startkey
    if endkey:
        view_args["endkey"] = endkey
    if key:
        view_args["keys"] = key

    def mk_params(title, aliases, text):
        return convert.ConvertParams(
            title=title,
            aliases=aliases,
            text=text,
            rtl=info.rtl,
            server=info.server,
            articlepath=info.articlepath,
            site_articlepath=info.articlepath,
            encoding=args.html_encoding,
            remove_embedded_bg=args.remove_embedded_bg,
            ensure_ext_image_urls=args.ensure_ext_image_urls,
        )

    def articles_from_viewiter(viewiter):
        for row in viewiter:
            if row and row.doc:
                try:
                    aliases = set()
                    for alias in row.doc.get("aliases", ()):
                        if isinstance(alias, list):
                            alias = tuple(alias)
                        aliases.add(alias)
                    if langlinks:
                        doc_langlinks = row.doc["parse"].get("langlinks", ())
                        for doc_langlink in doc_langlinks:
                            ll_lang = doc_langlink.get("lang")
                            ll_title = doc_langlink.get("*")
                            if ll_lang and ll_lang in langlinks and ll_title:
                                aliases.add(ll_title)
                    result = mk_params(
                        title=row.id,
                        aliases=aliases,
                        text=row.doc["parse"]["text"]["*"],
                    )
                except Exception:
                    log.exception(repr(row.doc))
                    result = mk_params(
                        title=row.id,
                        aliases=(),
                        text=None,
                    )
                yield result

    if key_file:
        with open(os.path.expanduser(key_file)) as f:
            for key_group in grouper(
                (line.strip().replace("_", " ") for line in f if line), 50
            ):
                query_args = dict(basic_view_args)
                query_args["keys"] = [key for key in key_group if key]
                keys_found = set()
                viewiter = couch.iterview(
                    "_all_docs", len(query_args["keys"]), **query_args
                )
                for item in articles_from_viewiter(viewiter):
                    keys_found.add(item[0])
                    yield item
                for key in set(query_args["keys"]) - keys_found:
                    yield mk_params(
                        title=key,
                        aliases=(),
                        text=None,
                    )
                keys_found.clear()

    else:
        viewiter = couch.iterview("_all_docs", 50, **view_args)
        for item in articles_from_viewiter(viewiter):
            yield item


def get_outname(args):
    outname = args.output_file
    if outname is None:
        basename = os.path.basename(args.couch_url)
        noext, _ = os.path.splitext(basename)
        outname = os.path.extsep.join((noext, "slob"))
    return outname


def get_siteinfo(args):
    couch, siteinfo_couch = mkcouch(args.couch_url)
    return siteinfo_couch[couch.name]
