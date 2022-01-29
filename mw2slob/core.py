import logging
import multiprocessing
import os
import sys
import time
from datetime import timedelta
from typing import Iterable
from typing import List
from typing import Mapping
from typing import Optional
from typing import Tuple

import slob

from . import convert
from . import siteinfo as si

times = {}


def begin(name):
    times[name] = time.time()


def end(name):
    t0 = times.pop(name)
    dt = timedelta(seconds=int(time.time() - t0))
    return dt


def p(text):
    sys.stdout.write(text)
    sys.stdout.flush()


def default_observer():
    def observer(e):
        if e.name == "begin_finalize":
            p("\nFinished adding content in %s" % end("content"))
            p("\nFinalizing...")
            begin("finalize")
        if e.name == "end_finalize":
            p("\nFinalized in %s" % end("finalize"))
        elif e.name == "begin_resolve_aliases":
            p("\nResolving aliases...")
            begin("aliases")
        elif e.name == "end_resolve_aliases":
            p("\nResolved aliases in %s" % end("aliases"))
        elif e.name == "begin_sort":
            p("\nSorting...")
            begin("sort")
        elif e.name == "end_sort":
            p(" sorted in %s" % end("sort"))

    return observer


class Defaults:
    compression = "lzma2"
    workdir = "."
    min_bin_size = 384
    observer = default_observer()
    no_math = False
    html_encoding = "utf-8"


log = logging.getLogger(__name__)

HTML_CHARSET_TMPL = "text/html;charset={0}"


SELECTORS = []
INTERWIKI: Mapping[str, str] = {}
NAMESPACES: Mapping[str, str] = {}


def process_initializer(css_selectors, interwikimap, namespaces):
    logging.basicConfig()
    for css_selector in css_selectors:
        if ":contains(" in css_selector:
            # selectors using :contains() can't be reused,
            # don't create instance here
            SELECTORS.append(css_selector)
        else:
            # creating selector instances for each article
            # appears to be expensive, create them once per process
            SELECTORS.append(convert.CSSSelector(css_selector))
    for item in interwikimap:
        prefix = item.get("prefix")
        url = item.get("url")
        if prefix and url:
            INTERWIKI[prefix] = url
    for item in namespaces.values():
        canonical = item.get("canonical")
        name = item.get("*")
        ns_id = item.get("id")
        if ns_id:
            if canonical:
                NAMESPACES[canonical] = ns_id
                NAMESPACES[canonical.lower()] = ns_id
            if name:
                NAMESPACES[name] = ns_id
                NAMESPACES[name.lower()] = ns_id


def safe_convert(
    params: convert.ConvertParams,
) -> Tuple[str, Iterable[str], Optional[bytes], Optional[str]]:
    text = params.text
    title = params.title
    aliases = params.aliases
    try:
        if text is None:
            return title, aliases, b"", None
        html = convert.convert(params, SELECTORS, NAMESPACES, INTERWIKI)
        return title, aliases, html, None
    except KeyboardInterrupt:
        raise
    except Exception as ex:
        log.exception("Failed to convert %r", title)
        return title, aliases, None, str(ex)


def run(
    slb: slob.Writer,
    articles: Iterable[convert.ConvertParams],
    filters: Iterable[str],
    interwikimap: Iterable[Mapping[str, str]],
    namespaces: Mapping[str, dict],
    html_encoding: str,
):
    pool = multiprocessing.Pool(
        None,
        process_initializer,
        [filters, interwikimap, namespaces],
    )
    html_content_type = HTML_CHARSET_TMPL.format(html_encoding)
    try:
        resulti = pool.imap_unordered(safe_convert, articles, chunksize=100)
        for title, aliases, text, error in resulti:
            if error:
                print(f"F {title}")
            else:
                if text:
                    keys = [title]
                    if aliases:
                        keys += aliases
                    slb.add(text, *keys, content_type=html_content_type)
                    print(f"S {title} ({len(text)})")
                else:
                    print(f"E {title}")
    except KeyboardInterrupt:
        log.warn("User interrupted")
    except:
        log.exception("")
        raise
    finally:
        pool.terminate()


def create_slob(
    outname: str,
    info: si.Info,
    articles: Iterable[convert.ConvertParams],
    content_dirs: Optional[List[str]] = None,
    compression=Defaults.compression,
    workdir=Defaults.workdir,
    min_bin_size=Defaults.min_bin_size,
    no_math=Defaults.no_math,
    observer=Defaults.observer,
    tags: Optional[Mapping[str, str]] = None,
    html_encoding=Defaults.html_encoding,
    filters: Iterable[str] = (),
):

    with slob.create(
        outname,
        compression=compression,
        workdir=workdir,
        min_bin_size=min_bin_size * 1024,
        observer=observer,
    ) as slb:
        begin("content")
        # create tags
        slb.tag("license.name", "")
        slb.tag("license.url", "")
        slb.tag("created.by", "")
        slb.tag("copyright", "")

        begin("all")

        # override article source
        if tags:
            for (name, value) in tags.items():
                slb.tag(name, value)

        run(slb, articles, filters, info.interwikimap, info.namespaces, html_encoding)

        include_built_in = {"js", "css", "images"}

        if not no_math:
            include_built_in.add("MathJax")

        content_dir = os.path.dirname(__file__)
        slob.add_dir(slb, content_dir, include_only=include_built_in, prefix="~/")
        if content_dirs:
            for content_dir in content_dirs:
                slob.add_dir(slb, content_dir)

    p("\nAll done in %s\n" % end("all"))
