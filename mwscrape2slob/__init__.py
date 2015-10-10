import argparse
import collections
import functools
import itertools
import json
import logging
import multiprocessing
import os
import re
import sys
import time

from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse, quote, unquote

import slob
import couchdb
import cssutils

import lxml.html
import lxml.html.clean
from lxml.html import builder as E

from lxml.cssselect import CSSSelector


CSSSelector = functools.partial(CSSSelector, translator='html')

log = logging.getLogger(__name__)

HTML_CHARSET_TMPL = 'text/html;charset={0}'
CSS = 'text/css'
JS = 'application/javascript'

MIME_TYPES = {
    "html": "text/html",
    "js": JS,
    "css": CSS,
    "json": "application/json",
    "woff": "application/font-woff",
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "ttf": "application/x-font-ttf",
    "otf": "application/x-font-opentype"
}

ConvertParams = collections.namedtuple(
    'ConvertParams', 'title aliases text rtl server articlepath args')


def read_file(name):
    with (open(os.path.join(os.path.dirname(__file__), name), 'rb')) as f:
        return f.read()

def default_filter_dir():
    return os.path.join(os.path.dirname(__file__), 'filters')

def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    args = [iter(iterable)] * n
    return itertools.izip_longest(fillvalue=fillvalue, *args)


def mkcouch(couch_url):
    parsed_url = urlparse(couch_url)
    couch_db = parsed_url.path.lstrip('/')
    server_url = parsed_url.scheme + '://'+ parsed_url.netloc
    server = couchdb.Server(server_url)
    print("Server:", server.resource.url)
    print("Database:", couch_db)
    return server[couch_db], server['siteinfo']


SELECTORS = []
INTERWIKI = {}
NAMESPACES = {}

def process_initializer(css_selectors, interwikimap, namespaces):
    logging.basicConfig()
    for css_selector in css_selectors:
        if ':contains(' in css_selector:
            #selectors using :contains() can't be reused,
            #don't create instance here
            SELECTORS.append(css_selector)
        else:
            #creating selector instances for each article
            #appears to be expensive, create them once per process
            SELECTORS.append(CSSSelector(css_selector))
    for item in interwikimap:
        prefix = item.get('prefix')
        url = item.get('url')
        if prefix and url:
            INTERWIKI[prefix] = url
    for _id, item in namespaces.items():
        canonical = item.get('canonical')
        name = item.get('*')
        ns_id = item.get('id')
        if ns_id:
            if canonical:
                NAMESPACES[canonical] = ns_id
                NAMESPACES[canonical.lower()] = ns_id
            if name:
                NAMESPACES[name] = ns_id
                NAMESPACES[name.lower()] = ns_id


class CouchArticleSource(collections.Sized):

    def __init__(self, args, slb):
        super(CouchArticleSource, self).__init__()
        self.couch, siteinfo_couch = mkcouch(args.couch_url)
        self.startkey = args.startkey
        self.endkey = args.endkey
        self.key = args.key
        self.key_file = args.key_file

        self.filters = []

        filter_dir = args.filter_dir
        if args.filter_file:
            for name in args.filter_file:
                full_name = os.path.expanduser(os.path.join(filter_dir, name))
                print('Reading filters from', full_name)
                with open(full_name) as f:
                    for selector in f:
                        selector = selector.strip()
                        if selector:
                            self.filters.append(selector)

        if args.filter:
            for selector in args.filter:
                self.filters.append(selector)

        log.info('Will apply following filters:\n%s', '\n'.join(self.filters))

        self.langlinks = args.langlinks

        self._metadata = {}
        self._metadata['siteinfo'] = siteinfo = siteinfo_couch[self.couch.name]

        self.interwikimap = siteinfo.get('interwikimap', [])

        article_namespaces = set(args.article_namespaces)

        self.namespaces = {
            ns.get('id'): ns for ns in siteinfo.get('namespaces', {}).values()
            if ns.get('id') and not (
                    ns.get('*') in article_namespaces or
                    ns.get('canonical') in article_namespaces)
        }

        general_siteinfo = siteinfo['general']
        sitename = general_siteinfo['sitename']
        sitelang = general_siteinfo['lang']
        rightsinfo = siteinfo['rightsinfo']
        self.rtl = 'rtl' in general_siteinfo

        if not slb.tags.get('license.name'):
            slb.tag('license.name', rightsinfo['text'])

        if not slb.tags.get('license.url'):
            license_url = rightsinfo['url']
            if license_url.startswith('//'):
                license_url = 'http:'+license_url
            slb.tag('license.url', license_url)

        articlepath = general_siteinfo.get('articlepath')
        if articlepath:
            articlepath = articlepath.split('$1', 1)[0]
        server = general_siteinfo.get('server', '')

        print('mw server: ', server)
        print('mw article path: ', articlepath)
        self.server = server
        self.articlepath = articlepath

        slb.tag('source', server)
        slb.tag('uri', server)
        slb.tag('label', '{} ({})'.format(sitename, sitelang))

        siteinfo_serialized = json.dumps(siteinfo, indent=2)
        slb.add(siteinfo_serialized.encode('utf-8'),
                '~/siteinfo.json',
                content_type='application/json')

        if self.langlinks:
            slb.tag('langlinks', ' '.join(sorted(self.langlinks)))

        self.args = args
        self.slb = slb


    def __len__(self):
        if self.key:
            return len(self.key)
        if self.key_file:
            with open(os.path.expanduser(self.key_file)) as f:
                return sum(1 for line in f if line)
        return self.couch.info()['doc_count']

    def run(self):
        basic_view_args = {
            'stale': 'ok',
            'include_docs': True
        }
        view_args = dict(basic_view_args)
        if self.startkey:
            view_args['startkey'] = self.startkey
        if self.endkey:
            view_args['endkey'] = self.endkey
        if self.key:
            view_args['keys'] = self.key

        def articles_from_viewiter(viewiter):
            for row in viewiter:
                if row and row.doc:
                    try:
                        aliases = set()
                        for alias in row.doc.get('aliases', ()):
                            if isinstance(alias, list):
                                alias = tuple(alias)
                            aliases.add(alias)
                        if self.langlinks:
                            doc_langlinks = row.doc['parse'].get('langlinks', ())
                            for doc_langlink in doc_langlinks:
                                ll_lang = doc_langlink.get('lang')
                                ll_title = doc_langlink.get('*')
                                if ll_lang and ll_lang in self.langlinks and ll_title:
                                    aliases.add(ll_title)
                        result = ConvertParams(
                            title=row.id,
                            aliases=aliases,
                            text=row.doc['parse']['text']['*'],
                            rtl=self.rtl,
                            server=self.server,
                            articlepath=self.articlepath,
                            args=self.args)
                    except Exception:
                        log.exception('')
                        result = ConvertParams(
                            title=row.id,
                            aliases=(),
                            text=None,
                            rtl=self.rtl,
                            server=self.server,
                            articlepath=self.articlepath,
                            args=self.args
                        )
                    yield result

        if self.key_file:
            def articles():
                with open(os.path.expanduser(self.key_file)) as f:
                    for key_group in grouper(
                            (line.strip().replace('_', ' ')
                             for line in f if line), 50):
                        query_args = dict(basic_view_args)
                        query_args['keys'] = [key for key in key_group if key]
                        keys_found = set()
                        viewiter = self.couch.iterview(
                            '_all_docs', len(query_args['keys']), **query_args)
                        for item in articles_from_viewiter(viewiter):
                            keys_found.add(item[0])
                            yield item
                        for key in set(query_args['keys']) - keys_found:
                            yield ConvertParams(title=key,
                                                aliases=(),
                                                text=None,
                                                rtl=self.rtl,
                                                server=self.server,
                                                articlepath=self.articlepath,
                                                args=self.args)
                        keys_found.clear()
        else:
            def articles():
                viewiter = self.couch.iterview(
                    '_all_docs', 50, **view_args)
                for item in articles_from_viewiter(viewiter):
                    yield item

        pool = multiprocessing.Pool(None, process_initializer, [
            self.filters,
            self.interwikimap,
            self.namespaces
        ])
        html_content_type = HTML_CHARSET_TMPL.format(self.args.html_encoding)
        try:
            resulti = pool.imap_unordered(safe_convert, articles())
            for title, aliases, text, error in resulti:
                if error:
                    print('F ' + title)
                else:
                    if text:
                        keys = [title]
                        if aliases:
                            keys += aliases
                        self.slb.add(
                            text, *keys,
                            content_type=html_content_type)
                        print('  ' + title)
                    else:
                        print('E ' + title)
        except KeyboardInterrupt:
            log.warn('User interrupted')
        except:
            log.exception('')
            raise
        finally:
            pool.terminate()


def safe_convert(params):
    (title, aliases, text, rtl, server, articlepath, args) = params
    try:
        if text is None:
            return title, aliases, '', None
        html = convert(title, text,
                       rtl, server, articlepath, args=args)
        return title, aliases, html, None
    except KeyboardInterrupt:
        raise
    except Exception as ex:
        log.exception('Failed to convert %r', title)
        return title, aliases, None, str(ex)


NEWLINE_RE = re.compile(r'[\n]{2,}')

SEL_IMG_TEX = CSSSelector('img.tex')
SEL_A_NEW = CSSSelector('a.new')
SEL_A_HREF_CITE = CSSSelector('a[href^="#cite"]')
SEL_A_IPA = CSSSelector('span.IPA>a')
SEL_MATH = CSSSelector('img.tex, .mwe-math-fallback-png-display, '
                       '.mwe-math-fallback-png-inline, '
                       '.mwe-math-fallback-source-display,'
                       '.mwe-math-fallback-source-inline, '
                       'strong.texerror')
SEL_HREF = CSSSelector('[href]')
SEL_SRC = CSSSelector('[src]')
SEL_ELEMENT_STYLE = CSSSelector('[style]')
SEL_GEO_NONDEFAULT = CSSSelector('.geo-nondefault')
SEL_GEO_MICROFORMAT = CSSSelector('.geo.microformat')
SEL_GEO_GEO_DMS = CSSSelector('.geo-geo-dms')

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
    safe_attrs_only=False)


def convert_url(url, server=None, articlepath='/wiki/',
                namespaces=None, interwiki=None):
    """
    >>> convert_url('/wiki/ABC#xyz')
    'ABC#xyz'

    >>> convert_url('/wiki/ABC/123#xyz')
    'ABC%2F123#xyz'

    >>> convert_url('/ABC', articlepath='/')
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

    """
    if namespaces is None:
        namespaces = NAMESPACES
    if interwiki is None:
        interwiki = INTERWIKI
    parsed = urlparse(url)._asdict()

    if parsed['netloc']:
        if not parsed['scheme']:
            parsed['scheme'] = 'http'
        return urlunparse(parsed.values())

    path = parsed['path']
    if parsed['query']:
        path += '?' + parsed['query']

    if path.startswith(articlepath):
        path = path[len(articlepath):]
        if ':' in path:
            prefix, _rest = path.split(':', 1)
            prefix = unquote(prefix)
            if prefix in namespaces and server:
                #Replace links to non-article namespaces
                #like Categories or  Appendix with external links
                return ''.join((server, url))
    else:
        prefix = parsed['scheme']
        if prefix and prefix in interwiki:
            url_template = interwiki[prefix]
            parsed_interwiki = urlparse(url_template)._asdict()
            parsed_interwiki['path'] = parsed_interwiki['path'].replace('$1', path)
            parsed_interwiki['fragment'] = parsed['fragment']
            if not parsed_interwiki['scheme']:
                parsed_interwiki['scheme'] = 'http'
            return urlunparse(parsed_interwiki.values())
    parsed['path'] = path.replace('/', '%2F').replace(':', '%3A')
    return urlunparse(parsed.values())

def convert_srcset(value):
    """
    >>> convert_srcset('mdn-logo-HD.png 2x, mdn-logo-small.png 15w, mdn-banner-HD.png 100w 2x')
    'mdn-logo-HD.png 2x, mdn-logo-small.png 15w, mdn-banner-HD.png 100w 2x'

    >>> convert_srcset('//example.com/mdn-logo-HD.png 2x, //example.com/mdn-logo-small.png 15w')
    'http://example.com/mdn-logo-HD.png 2x, http://example.com/mdn-logo-small.png 15w'

    >>> convert_srcset('http://example.com/mdn-logo-HD.png 2x, //example.com/mdn-logo-small.png 15w')
    'http://example.com/mdn-logo-HD.png 2x, http://example.com/mdn-logo-small.png 15w'

    >>> convert_srcset('http://example.com/mdn-logo-HD.png 2x, http://example.com/mdn-logo-small.png 15w')
    'http://example.com/mdn-logo-HD.png 2x, http://example.com/mdn-logo-small.png 15w'

    """
    parts = value.split(',')
    converted = []
    for part in parts:
        if part.lstrip().startswith('//'):
            converted.append(part.replace('//', 'http://', 1))
        else:
            converted.append(part)
    return ','.join(converted)


def mkgeolink(latitude, longitude):
    return E.A(
        E.IMG(E.CLASS('mwscrape2slob-geo-link-icon'),
              src='~/images/Globe.svg'),
        href='geo:{},{}'.format(latitude.strip(), longitude.strip()))


def convert_geo_microformat(doc, selector=SEL_GEO_NONDEFAULT,
                            drop_parent_tree=True):
    for geo_nondefault in selector(doc):
        geo_items = geo_nondefault.cssselect('.geo')
        for geo in geo_items:
            coords = geo.text
            if coords and ';' in coords:
                latitude, longitude = coords.split(';', 1)
                a = mkgeolink(latitude, longitude)
                geo_nondefault.getparent().addnext(a)
        if drop_parent_tree:
            geo_nondefault.drop_tree()
        else:
            for geo_dec in geo_nondefault.cssselect('.geo-dec'):
                geo_dec.drop_tree()


def convert_geo_microformat2(doc):
    for geo in SEL_GEO_MICROFORMAT(doc):
        latitude = geo.cssselect('.latitude')
        longitude = geo.cssselect('.longitude')
        if latitude and longitude:
            latitude = latitude[0].text
            longitude = longitude[0].text
            a = mkgeolink(latitude, longitude)
            geo.addnext(a)
            geo.drop_tree()


def convert_geo_microformat3(doc):
    convert_geo_microformat(doc,
                            selector=SEL_GEO_GEO_DMS,
                            drop_parent_tree=False)


def convert(title, text, rtl, server, articlepath, args):

    encoding = args.html_encoding if args else 'utf-8'

    text = NEWLINE_RE.sub('\n', text)
    doc = lxml.html.fromstring(text)

    CLEANER(doc)

    for convert_geo in (convert_geo_microformat,
                        convert_geo_microformat2,
                        convert_geo_microformat3):
        try:
            convert_geo(doc)
        except Exception:
            log.exception('Failed to convert geo')


    for selector in SELECTORS:
        if isinstance(selector, str):
            selector = CSSSelector(selector)
        for item in selector(doc):
            item.drop_tree()

    for item in SEL_A_IPA(doc):
        item.drop_tag()

    for item in SEL_A_NEW(doc):
        item.drop_tag()

    for sel_element_with_style in selector_list(args.remove_embedded_bg):
        for item in sel_element_with_style(doc):
            style = item.attrib['style']
            try:
                ss = cssutils.parseStyle(style)
            except Exception:
                log.exception('Failed to parse style attr with value %r', style)
            else:
                ss.backgroundColor = None
                ss.background = None
                item.attrib['style'] = ss.cssText


    for item in SEL_HREF(doc):
        item.attrib['href'] = convert_url(item.attrib['href'],
                                          server=server,
                                          articlepath=articlepath)

    for item in SEL_SRC(doc):
        item.attrib['src'] = convert_url(item.attrib['src'],
                                         server=server,
                                         articlepath=articlepath)

        if 'srcset' in item.attrib:
            srcset = item.attrib['srcset']
            if srcset:
                item.attrib['srcset'] = convert_srcset(srcset)

    has_math = len(SEL_MATH(doc)) > 0

    if has_math:
        for item in SEL_IMG_TEX(doc):
            item.attrib.pop('srcset', None)
            item.attrib.pop('src', None)

    if server and articlepath:
        article_url = ''.join((server, articlepath, quote(title)))
        a = E.A(id="view-online-link", href=article_url)
        title_heading = doc.cssselect('h1')
        if len(title_heading) > 0:
            title_heading = title_heading[0]
            if title_heading.text:
                a.text = title_heading.text
                title_heading.text = ''
                title_heading.append(a)
        else:
            a.text = title
            title_heading = E.H1()
            title_heading.append(a)
            body = doc.find('body')
            if not body is None:
                body.insert(0, title_heading)
            else:
                doc.insert(0, title_heading)

    if has_math:
        math_jax = (
            '<script src="~/js/jquery-2.1.3.min.js"></script>'
            '<script src="~/MathJax/MathJax.js"></script>'
            '<script src="~/MathJax/MediaWiki.js"></script>'
        )
    else:
        math_jax = ''

    result = ''.join((
        '<script src="~/js/styleswitcher.js"></script>',
        '<link rel="stylesheet" href="~/css/shared.css" type="text/css">',
        '<link rel="stylesheet" href="~/css/mediawiki_shared.css" type="text/css">',
        '<link rel="stylesheet" href="~/css/mediawiki_monobook.css" type="text/css">',
        '<link rel="alternate stylesheet" href="~/css/night.css" type="text/css" title="Night">',
        math_jax,
        '<div dir="rtl" class="rtl">' if rtl else '',
        lxml.html.tostring(doc, encoding='unicode'),
        '</div>' if rtl else '',
    )) .encode(encoding)

    return result


def selector_list(str_value):
    if str_value:
        return [CSSSelector(s) for s in str_value.split(',')]
    else:
        return []


def parse_args():

    arg_parser = argparse.ArgumentParser()

    arg_parser.add_argument(
        '-s', '--startkey',
        help='Skip articles with titles before this one when sorted')

    arg_parser.add_argument(
        '-e', '--endkey',
        help='Stop processing when this title is reached')

    arg_parser.add_argument(
        '-k', '--key', nargs="+",
        help='Process specified keys only')

    arg_parser.add_argument(
        '-K', '--key-file',
        help='Process only keys specified in file')

    arg_parser.add_argument(
        '-f', '--filter-file', nargs='+',
        help=('Name of filter file. Filter file consists of '
              'CSS selectors (see cssselect documentation '
              'for description of supported selectors), '
              'one selector per line. '))

    arg_parser.add_argument(
        '-F', '--filter', nargs='+',
        help=('CSS selectors for elements to exclude '
              '(see cssselect documentation '
              'for description of supported selectors)'))

    arg_parser.add_argument('couch_url', type=str,
                            help='URL of CouchDB created by '
                            'mwscrape to be used as input')

    arg_parser.add_argument('-o', '--output-file', type=str,
                            help='Name of output slob file')

    arg_parser.add_argument('-c', '--compression',
                            choices=['lzma2', 'zlib'],
                            default='lzma2',
                            help='Name of compression to use. Default: %(default)s')

    arg_parser.add_argument('-b', '--bin-size',
                            type=int,
                            default=384,
                            help=('Minimum storage bin size in kilobytes. '
                                  'Default: %(default)s'))

    arg_parser.add_argument('-u', '--uri', type=str,
                            default='',
                            help=('Value for uri tag. Slob-specific '
                                  'article URLs such as bookmarks can be '
                                  'migrated to another slob based on '
                                  'matching "uri" tag values'))

    arg_parser.add_argument('-l', '--license-name', type=str,
                            default='',
                            help=('Value for license.name tag. '
                                  'This should be name under which '
                                  'the license is commonly known.'))

    arg_parser.add_argument('-L', '--license-url', type=str,
                            default='',
                            help=('Value for license.url tag. '
                                  'This should be a URL for license text'))

    arg_parser.add_argument('-ll', '--langlinks',
                            default=None,
                            nargs='+',
                            help=('Include article titles from Wikipedia '
                                  'language links for these languages if available'))

    arg_parser.add_argument('-a', '--created-by', type=str,
                            default='',
                            help=('Value for created.by tag. '
                                  'Identifier (e.g. name or email) '
                                  'for slob file creator'))

    arg_parser.add_argument('-w', '--work-dir', type=str, default='.',
                            help=('Directory for temporary files '
                                  'created during compilation. '
                                  'Default: %(default)s'))

    arg_parser.add_argument('--filter-dir', type=str,
                            default=default_filter_dir(),
                            help=('Directory where filter files '
                                  'are located. '
                                  'Default: filters directory in this package'))

    arg_parser.add_argument('--html-encoding', type=str, default='utf-8',
                            help=('HTML text encoding. '
                                  'Default: %(default)s'))

    arg_parser.add_argument('--remove-embedded-bg', type=str, default='',
                            help=('Comma separated list of CSS selectors. '
                                  'Background will be removed from matching '
                                  'element\'s style attribute. For example, to '
                                  'remove background from all elements with style attribute'
                                  'specify selector [style]. '
                                  'Default: %(default)s'))

    arg_parser.add_argument('--content-dir', dest="content_dirs", nargs='+',
                            help=('Add content from directory, using full path as key'))

    arg_parser.add_argument('--article-namespace', dest="article_namespaces", nargs='+',
                            help=('Treat specified Mediawiki namespaces as articles'))

    return arg_parser.parse_args()


def main():

    logging.basicConfig()

    def p(text):
        sys.stdout.write(text)
        sys.stdout.flush()

    times = {}

    def begin(name):
        times[name] = time.time()

    def end(name):
        t0 = times.pop(name)
        dt = timedelta(seconds=int(time.time() - t0))
        return dt

    def observer(e):
        if e.name == 'begin_finalize':
            p('\nFinished adding content in %s' % end('content'))
            p('\nFinalizing...')
            begin('finalize')
        if e.name == 'end_finalize':
            p('\nFinalized in %s' % end('finalize'))
        elif e.name == 'begin_resolve_aliases':
            p('\nResolving aliases...')
            begin('aliases')
        elif e.name == 'end_resolve_aliases':
            p('\nResolved aliases in %s' % end('aliases'))
        elif e.name == 'begin_sort':
            p('\nSorting...')
            begin('sort')
        elif e.name == 'end_sort':
            p(' sorted in %s' % end('sort'))

    args = parse_args()

    outname = args.output_file
    if outname is None:
        basename = os.path.basename(args.couch_url)
        noext, _ext = os.path.splitext(basename)
        outname = os.path.extsep.join((noext, args.compression, 'slob'))

    def set_tag_from_args(slb, name):
        value = getattr(args, name.replace('.', '_'))
        if value:
            slb.tag(name, value)

    with slob.create(outname,
                     compression=args.compression,
                     workdir=args.work_dir,
                     min_bin_size=args.bin_size*1024,
                     observer=observer) as slb:
        begin('content')
        #create tags
        slb.tag('license.name', '')
        slb.tag('license.url', '')
        slb.tag('created.by', '')
        slb.tag('copyright', '')
        article_source = CouchArticleSource(args, slb)
        begin('all')
        #command args override article source
        set_tag_from_args(slb, 'license.name')
        set_tag_from_args(slb, 'license.url')
        set_tag_from_args(slb, 'created.by')

        article_source.run()

        content_dir = os.path.dirname(__file__)
        slob.add_dir(slb, content_dir,
                     include_only={'js', 'css', 'images', 'MathJax'},
                     prefix='~/')
        if args.content_dirs:
            for content_dir in args.content_dirs:
                slob.add_dir(slb, content_dir)


    p('\nAll done in %s\n' % end('all'))
