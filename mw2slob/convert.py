import collections
import functools
import logging
import re
from typing import Iterable
from typing import Mapping
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlparse
from urllib.parse import urlunparse

import cssutils
import lxml.html
import lxml.html.clean
from lxml.cssselect import CSSSelector
from lxml.html import builder as E
from lxml.html.soupparser import fromstring

CSSSelector = functools.partial(CSSSelector, translator="html")

log = logging.getLogger(__name__)

ConvertParams = collections.namedtuple(
    "ConvertParams",
    [
        "title",
        "aliases",
        "text",
        "rtl",
        "server",
        # actual article path in article html,
        # differs from site article path in HTML dumps
        "articlepath",
        # external article path, as in online version
        "site_articlepath",
        "encoding",
        "remove_embedded_bg",
        "ensure_ext_image_urls",
    ],
)

NEWLINE_RE = re.compile(r"[\n]{2,}")

SEL_IMG_TEX = CSSSelector("img.tex,img.mwe-math-fallback-image-inline")
SEL_A_NEW = CSSSelector("a.new")
SEL_A_HREF_CITE = CSSSelector('a[href^="#cite"]')
SEL_A_IPA = CSSSelector("span.IPA>a")
SEL_MATH = CSSSelector(
    "img.tex, .mwe-math-fallback-png-display, "
    ".mwe-math-fallback-image-inline, "
    ".mwe-math-fallback-png-inline, "
    ".mwe-math-fallback-source-display,"
    ".mwe-math-fallback-source-inline, "
    "strong.texerror"
)
SEL_HREF = CSSSelector("[href]")
SEL_SRC = CSSSelector("[src]")
SEL_ELEMENT_STYLE = CSSSelector("[style]")
SEL_GEO_NONDEFAULT = CSSSelector(".geo-nondefault")
SEL_GEO_MICROFORMAT = CSSSelector(".geo")
SEL_GEO_GEO_DMS = CSSSelector(".geo-geo-dms")

# Enterprise HTML dump
SEL_ONLINE_LINK = CSSSelector('link[rel="dc:isVersionOf"]')
SEL_DOCUMENT_BASE = CSSSelector("base")
SEL_HEAD = CSSSelector("head")
SEL_WITH_DATA_MW_ATTR = CSSSelector("[data-mw]")
SEL_WITH_DATA_MW_SECTION_ID = CSSSelector("section[data-mw-section-id]")
SEL_WITH_ATTR_ID = CSSSelector("[id]")
SEL_WITH_ATTR_TYPEOF = CSSSelector("[typeof]")
SEL_WITH_ATTR_ABOUT = CSSSelector("[about]")
SEL_WITH_ATTR_TITLE = CSSSelector("[title]")
SEL_A_WITH_ATTR_REL = CSSSelector("a[rel]")
SEL_LINKS_ELEMENTS = CSSSelector("link")

CLEANER = lxml.html.clean.Cleaner(
    comments=True,
    scripts=True,
    javascript=True,
    style=False,
    links=False,
    meta=True,
    processing_instructions=True,
    embedded=True,
    page_structure=True,
    safe_attrs_only=False,
)


IMG_EXTENSIONS = {"jpg", "jpeg", "png", "svg", "gif", "bmp"}


def is_image(path):
    """
    >>> is_image('/a/bb/ccc/file.jpg')
    True

    >>> is_image('/a/jpg')
    False

    >>> is_image('/a/jpg.pdf')
    False

    """
    parts = path.rsplit(".", 1)
    if len(parts) == 2:
        ext = parts[1].lower()
        return ext in IMG_EXTENSIONS
    return False


def replace_article_path(articlepath, site_articlepath, relative_url):
    """
    >>> replace_article_path("./", "/wiki/", "./File:xyz.jpg")
    '/wiki/File:xyz.jpg'
    >>> replace_article_path("/wiki/", "/wiki/", "/wiki/File:xyz.jpg")
    '/wiki/File:xyz.jpg'
    """
    stripped_articlepath = relative_url[len(articlepath) :]
    return f"{site_articlepath}{stripped_articlepath}"


def mk_ext_url(server, articlepath, site_articlepath, relative_url):
    return "".join(
        (server, replace_article_path(articlepath, site_articlepath, relative_url))
    )


def convert_url(
    url,
    server=None,
    articlepath="/wiki/",
    site_articlepath=None,
    namespaces=None,
    interwiki=None,
    ensure_ext_image_urls=False,
):
    """
    >>> convert_url('/wiki/ABC#xyz')
    'ABC#xyz'

    >>> convert_url('/wiki/ABC/123#xyz')
    'ABC%2F123#xyz'

    >>> convert_url('/ABC', articlepath='/')
    'ABC'

    >>> convert_url('./ABC', articlepath='./')
    'ABC'

    >>> convert_url('./ABC', articlepath='./', server="http://simple.wikipedia.org")
    'ABC'

    >>> convert_url('//example.com/ABC', articlepath='/')
    'http://example.com/ABC'


    >>> convert_url('ABC')
    'ABC'

    >>> convert_url('w:ABC', interwiki=dict(w='http://en.wikipedia.org/wiki/$1'))
    'http://en.wikipedia.org/wiki/ABC'

    >>> convert_url('/wiki/%D0%A4%D0%B0%D0%B9%D0%BB:ABC.gif', server='http://ru.wikipedia.org', namespaces={'Файл'})
    'http://ru.wikipedia.org/wiki/%D0%A4%D0%B0%D0%B9%D0%BB:ABC.gif'

    >>> convert_url('http://images.uncyclomedia.co/uncyclopedia/en/thumb/a/ac/Melone-Cesare-Borgia-BR600.jpg/300px-Melone-Cesare-Borgia-BR600.jpg')
    'http://images.uncyclomedia.co/uncyclopedia/en/thumb/a/ac/Melone-Cesare-Borgia-BR600.jpg/300px-Melone-Cesare-Borgia-BR600.jpg'

    >>> convert_url('/wiki/%D0%A4%D0%B0%D0%B9%D0%BB:ABC.gif', server='http://ru.wikipedia.org', ensure_ext_image_urls=True)
    'http://ru.wikipedia.org/wiki/%D0%A4%D0%B0%D0%B9%D0%BB:ABC.gif'

    """
    if site_articlepath is None:
        site_articlepath = articlepath
    if namespaces is None:
        namespaces = {}
    if interwiki is None:
        interwiki = {}
    parsed = urlparse(url)._asdict()

    if parsed["netloc"]:
        if not parsed["scheme"]:
            parsed["scheme"] = "http"
        return urlunparse(tuple(parsed.values()))

    path = parsed["path"]

    if ensure_ext_image_urls and is_image(path):
        return mk_ext_url(server, articlepath, site_articlepath, url)

    if parsed["query"]:
        path += "?" + parsed["query"]

    if path.startswith(articlepath):
        path = path[len(articlepath) :]
        if ":" in path:
            prefix, _ = path.split(":", 1)
            prefix = unquote(prefix)
            if prefix in namespaces and server:
                # Replace links to non-article namespaces
                # like Categories or  Appendix with external links
                return mk_ext_url(server, articlepath, site_articlepath, url)
    else:
        prefix = parsed["scheme"]
        if prefix and prefix in interwiki:
            url_template = interwiki[prefix]
            parsed_interwiki = urlparse(url_template)._asdict()
            parsed_interwiki["path"] = parsed_interwiki["path"].replace("$1", path)
            parsed_interwiki["fragment"] = parsed["fragment"]
            if not parsed_interwiki["scheme"]:
                parsed_interwiki["scheme"] = "http"
            return urlunparse(tuple(parsed_interwiki.values()))
    parsed["path"] = path.replace("/", "%2F").replace(":", "%3A").replace("_", "%20")
    return urlunparse(tuple(parsed.values()))


def convert_srcset(value, **kwargs):
    """
    >>> convert_srcset('mdn-logo-HD.png 2x, mdn-logo-small.png 15w, mdn-banner-HD.png 100w 2x')
    'mdn-logo-HD.png 2x, mdn-logo-small.png 15w, mdn-banner-HD.png 100w 2x'

    >>> convert_srcset('//example.com/mdn-logo-HD.png 2x, //example.com/mdn-logo-small.png 15w')
    'http://example.com/mdn-logo-HD.png 2x, http://example.com/mdn-logo-small.png 15w'

    >>> convert_srcset('http://example.com/mdn-logo-HD.png 2x, //example.com/mdn-logo-small.png 15w')
    'http://example.com/mdn-logo-HD.png 2x, http://example.com/mdn-logo-small.png 15w'

    >>> convert_srcset('http://example.com/mdn-logo-HD.png 2x, http://example.com/mdn-logo-small.png 15w')
    'http://example.com/mdn-logo-HD.png 2x, http://example.com/mdn-logo-small.png 15w'

    >>> convert_srcset("https://maps.wikimedia.org/img/osm-intl,12,a,a,270x200@2x.png?lang=en&amp;domain=simple.wikipedia.org&amp;title=Rebeuvelier&amp;groups=_69ef66da20df012d8c85e16fa2be4e060917327c")
    'https://maps.wikimedia.org/img/osm-intl,12,a,a,270x200@2x.png?lang=en&amp;domain=simple.wikipedia.org&amp;title=Rebeuvelier&amp;groups=_69ef66da20df012d8c85e16fa2be4e060917327c'
    """
    parts = value.split(", ")
    converted = []
    for part in parts:
        subparts = part.strip().split(" ", 1)
        subparts[0] = convert_url(subparts[0], **kwargs)
        converted.append(" ".join(subparts))
    return ", ".join(converted)


def mkgeolink(latitude, longitude):
    return E.A(
        E.IMG(E.CLASS("mwscrape2slob-geo-link-icon"), src="~/images/Globe.svg"),
        href="geo:{},{}".format(latitude.strip(), longitude.strip()),
    )


def convert_geo_microformat(doc, selector=SEL_GEO_NONDEFAULT, drop_parent_tree=True):
    for geo_nondefault in selector(doc):
        geo_items = geo_nondefault.cssselect(".geo")
        for geo in geo_items:
            coords = geo.text
            if coords and ";" in coords:
                latitude, longitude = coords.split(";", 1)
                a = mkgeolink(latitude, longitude)
                geo_nondefault.getparent().addnext(a)
        if drop_parent_tree:
            geo_nondefault.drop_tree()
        else:
            for geo_dec in geo_nondefault.cssselect(".geo-dec"):
                geo_dec.drop_tree()


def convert_geo_microformat2(doc):
    for geo in SEL_GEO_MICROFORMAT(doc):
        latitude = geo.cssselect(".latitude")
        longitude = geo.cssselect(".longitude")
        if latitude and longitude:
            latitude = latitude[0].text
            longitude = longitude[0].text
            a = mkgeolink(latitude, longitude)
            geo.addnext(a)
            geo.drop_tree()


def convert_geo_microformat3(doc):
    convert_geo_microformat(doc, selector=SEL_GEO_GEO_DMS, drop_parent_tree=False)


MATH_JAX_SCRIPTS = (
    '<script src="~/js/jquery-2.1.3.min.js"></script>'
    '<script src="~/MathJax/MathJax.js"></script>'
    '<script src="~/MathJax/MediaWiki.js"></script>'
)

CSS_LINKS = (
    '<script src="~/js/styleswitcher.js"></script>'
    '<link rel="stylesheet" href="~/css/shared.css" type="text/css">'
    '<link rel="stylesheet" href="~/css/mediawiki_shared.css" type="text/css">'
    '<link rel="stylesheet" href="~/css/mediawiki_monobook.css" type="text/css">'
    '<link rel="alternate stylesheet" href="~/css/night.css" type="text/css" title="Night">'
)


def wrap_rtl(text):
    return f'<div dir="rtl" class="rtl">{text}</div>'


def convert(
    params: ConvertParams,
    filters: Iterable,
    namespaces: Mapping[str, str],
    interwiki: Mapping[str, str],
):
    (
        title,
        _,
        text,
        rtl,
        server,
        articlepath,
        site_articlepath,
        encoding,
        remove_embedded_bg,
        ensure_ext_image_urls,
    ) = params
    text = NEWLINE_RE.sub("\n", text)
    doc = fromstring(text)

    x_url = functools.partial(
        convert_url,
        server=server,
        articlepath=articlepath,
        site_articlepath=site_articlepath,
        ensure_ext_image_urls=ensure_ext_image_urls,
        namespaces=namespaces,
        interwiki=interwiki,
    )

    x_srcset = functools.partial(
        convert_srcset,
        server=server,
        articlepath=articlepath,
        site_articlepath=site_articlepath,
        ensure_ext_image_urls=ensure_ext_image_urls,
        namespaces=namespaces,
        interwiki=interwiki,
    )

    CLEANER(doc)

    for convert_geo in (
        convert_geo_microformat,
        convert_geo_microformat2,
        convert_geo_microformat3,
    ):
        try:
            convert_geo(doc)
        except Exception:
            log.exception("Failed to convert geo")

    for selector in filters:
        if isinstance(selector, str):
            selector = CSSSelector(selector)
        for item in selector(doc):
            item.drop_tree()

    for item in SEL_HEAD(doc):
        item.drop_tree()

    for item in SEL_DOCUMENT_BASE(doc):
        item.drop_tree()

    for item in SEL_A_IPA(doc):
        item.drop_tag()

    for item in SEL_A_NEW(doc):
        item.drop_tag()

    for sel_element_with_style in selector_list(remove_embedded_bg):
        for item in sel_element_with_style(doc):
            style = item.attrib["style"]
            try:
                ss = cssutils.parseStyle(style)
            except Exception:
                log.exception("Failed to parse style attr with value %r", style)
            else:
                ss.backgroundColor = None
                ss.background = None
                item.attrib["style"] = ss.cssText

    for item in SEL_HREF(doc):
        item.attrib["href"] = x_url(item.attrib["href"])

    for item in SEL_SRC(doc):
        item.attrib["src"] = x_url(item.attrib["src"])

        if "srcset" in item.attrib:
            srcset = item.attrib["srcset"]
            if srcset:
                item.attrib["srcset"] = x_srcset(srcset)

    for item in SEL_WITH_DATA_MW_ATTR(doc):
        item.attrib.pop("data-mw")
    for item in SEL_WITH_DATA_MW_SECTION_ID(doc):
        item.attrib.pop("data-mw-section-id")
    for item in SEL_WITH_ATTR_ID(doc):
        if item.attrib["id"].startswith("mw"):
            item.attrib.pop("id")
    for item in SEL_WITH_ATTR_TYPEOF(doc):
        item.attrib.pop("typeof")
    for item in SEL_A_WITH_ATTR_REL(doc):
        item.attrib.pop("rel")
    for item in SEL_WITH_ATTR_ABOUT(doc):
        item.attrib.pop("about")
    for item in SEL_WITH_ATTR_TITLE(doc):
        item.attrib.pop("title")

    has_math = len(SEL_MATH(doc)) > 0

    if has_math:
        for item in SEL_IMG_TEX(doc):
            item.attrib.pop("srcset", None)
            item.attrib.pop("src", None)

    article_link_elements = SEL_ONLINE_LINK(doc)
    has_article_link = len(article_link_elements) > 0
    if has_article_link or (server and articlepath):
        if has_article_link:
            article_url = article_link_elements[0].attrib["href"]
            article_link_elements[0].tail = None
        else:
            article_url = "".join((server, site_articlepath, quote(title)))
        a = E.A(id="view-online-link", href=article_url)
        title_heading = doc.cssselect("h1")
        if len(title_heading) > 0:
            title_heading = title_heading[0]
            if title_heading.text:
                a.text = title_heading.text
                title_heading.text = ""
                title_heading.append(a)
        else:
            a.text = title
            title_heading = E.H1()
            title_heading.append(a)
            body = doc.find("body")
            if not body is None:
                body.insert(0, title_heading)
            else:
                doc.insert(0, title_heading)

    for item in SEL_LINKS_ELEMENTS(doc):
        item.drop_tree()

    math_jax = MATH_JAX_SCRIPTS if has_math else ""
    serialized = str(lxml.html.tostring(doc, encoding="unicode"))
    result = "".join(
        (CSS_LINKS, math_jax, wrap_rtl(serialized) if rtl else serialized)
    ).encode(encoding)

    return result


def selector_list(str_value):
    if str_value:
        return [CSSSelector(s) for s in str_value.split(",")]
    else:
        return []
