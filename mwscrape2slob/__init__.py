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
from urllib.parse import urlparse, quote

import slob
import couchdb

import lxml.html
import lxml.html.clean
from lxml.html import builder as E

from lxml.cssselect import CSSSelector

CSSSelector = functools.partial(CSSSelector, translator='html')

log = logging.getLogger(__name__)

HTML = 'text/html; charset=utf-8'
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
    "ttf": "application/x-font-ttf",
    "otf": "application/x-font-opentype"
}

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
    for css_selector in css_selectors:
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
        self.namespaces = siteinfo.get('namespaces', {})
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


        article_path = general_siteinfo.get('articlepath')
        server = general_siteinfo.get('server', '')

        if server and article_path:
            article_url_template = server + article_path
        else:
            article_url_template = None

        self.article_url_template = article_url_template

        slb.tag('source', server)
        slb.tag('uri', server)
        slb.tag('label', '{} ({})'.format(sitename, sitelang))

        siteinfo_serialized = json.dumps(siteinfo, indent=2)
        slb.add(siteinfo_serialized.encode('utf-8'),
                '~/siteinfo.json',
                content_type='application/json')

        if self.langlinks:
            slb.tag('langlinks', ' '.join(sorted(self.langlinks)))

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
                        aliases = set(row.doc.get('aliases', ()))
                        if self.langlinks:
                            doc_langlinks = row.doc['parse'].get('langlinks', ())
                            for doc_langlink in doc_langlinks:
                                ll_lang = doc_langlink.get('lang')
                                ll_title = doc_langlink.get('*')
                                if ll_lang and ll_lang in self.langlinks and ll_title:
                                    aliases.add(ll_title)
                        result = (row.id, aliases,
                                  row.doc['parse']['text']['*'], self.rtl,
                                  self.article_url_template)
                    except Exception:
                        result = row.id, None, None, False, None
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
                        for key in (set(query_args['keys']) - keys_found):
                            yield key, None, None, False, None
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
                        self.slb.add(text, *keys, content_type=HTML)
                        print('  ' + title)
                    else:
                        print('E ' + title)
        except:
            log.exception('')
            raise
        finally:
            pool.terminate()


def safe_convert(params):
    (title, aliases, text, rtl, article_url_template) = params
    try:
        if text is None:
            return title, aliases, '', None
        html = convert(title, text,
                        rtl=rtl,
                        article_url_template=article_url_template)
        return title, aliases, html, None
    except KeyboardInterrupt:
        raise
    except Exception as ex:
        log.exception('Failed to convert %r', title)
        return title, aliases, None, str(ex)


NEWLINE_RE = re.compile(r'[\n]{2,}')

SEL_IMG_TEX = CSSSelector('img.tex')
SEL_A_NEW = CSSSelector('a.new')
SEL_A = CSSSelector('a')
SEL_A_HREF_WIKI = CSSSelector('a[href^="/wiki/"]')
SEL_A_HREF_NO_PROTO = CSSSelector('a[href^="//"]')
SEL_IMG_SRC_NO_PROTO = CSSSelector('img[src^="//"]')
SEL_A_HREF_CITE = CSSSelector('a[href^="#cite"]')
SEL_A_IMAGE = CSSSelector('a.image')
SEL_MATH = CSSSelector('img.tex, .mwe-math-fallback-png-display, '
                       '.mwe-math-fallback-png-inline, '
                       '.mwe-math-fallback-source-display,'
                       '.mwe-math-fallback-source-inline, '
                       'strong.texerror')


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


def convert(title, text, rtl=False, article_url_template=None):

    text = NEWLINE_RE.sub('\n', text)
    doc = lxml.html.fromstring(text)

    CLEANER(doc)

    for selector in SELECTORS:
        for item in selector(doc):
            item.drop_tree()

    for item in SEL_A_IMAGE(doc):
        item.drop_tag()

    for item in SEL_A_NEW(doc):
        item.attrib.pop('href', None)

    for item in SEL_A_HREF_WIKI(doc):
        item.attrib['href'] = item.attrib['href'].replace('/wiki/', '')

    for item in SEL_A_HREF_NO_PROTO(doc):
        item.attrib['href'] = 'http:' + item.attrib['href']

    for item in SEL_IMG_SRC_NO_PROTO(doc):
        item.attrib['src'] = 'http:' + item.attrib['src']
        if 'srcset' in item.attrib:
            item.attrib['srcset'] = item.attrib['srcset'].replace('//', 'http://')

    for item in SEL_A(doc):
        href = item.attrib.get('href')
        if href:
            parsed = urlparse(href)
            url_template = None
            if article_url_template and parsed.scheme in NAMESPACES:
                url_template = article_url_template.replace('$1',
                                                            parsed.scheme + ':$1')
            if parsed.scheme in INTERWIKI:
                url_template = INTERWIKI[parsed.scheme]
            if url_template:
                new_href = url_template.replace('$1', parsed.path)
                if parsed.fragment:
                    new_href = '#'.join((new_href, parsed.fragment))
                print('{}: {} -> {}'.format(title, href, new_href))
                item.attrib['href'] = new_href


    has_math = len(SEL_MATH(doc)) > 0

    if has_math:
        for item in SEL_IMG_TEX(doc):
            item.attrib.pop('srcset', None)
            item.attrib.pop('src', None)

    if article_url_template:
        article_url = article_url_template.replace(
            '$1', quote(title))
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
            '<script src="~/js/jquery-2.1.1.min.js"></script>'
            '<script src="~/MathJax/MathJax.js"></script>'
            '<script src="~/js/mathjax-config.js"></script>'
        )
    else:
        math_jax = ''

    result = ''.join((
        '<html>'
        '<head>',
        math_jax,
        '<link rel="stylesheet" href="~/css/shared.css" type="text/css"></link>',
        '<link rel="stylesheet" href="~/css/mediawiki_shared.css" type="text/css"></link>',
        '<link rel="stylesheet" href="~/css/mediawiki_monobook.css" type="text/css"></link>',
        '<link rel="alternate stylesheet" href="~/css/night.css" type="text/css" title="Dark"></link>',
        '</head>'
        '<body>',
        '<div dir="rtl" class="rtl">' if rtl else '',
        lxml.html.tostring(doc, encoding='unicode'),
        '</div>' if rtl else '',
        '</body>',
        '</html>'
    )) .encode('utf-8')

    return result


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
                            default='zlib',
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

    return arg_parser.parse_args()



def add_dir(slb, topdir, prefix='~/'):
    print('Adding', topdir)
    for item in os.walk(topdir):
        dirpath, _dirnames, filenames = item
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            _, ext = os.path.splitext(filename)
            ext = ext.lstrip(os.path.extsep)
            content_type = MIME_TYPES.get(ext.lower())
            if not content_type:
                print('Content type for file name '
                      'extension {} is unknown'.format('ext'))
            else:
                with open(full_path, 'rb') as f:
                    content = f.read()
                    key = prefix + full_path
                    slb.add(content, key, content_type=content_type)


def main():

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
            p('\nFinilized in %s' % end('finalize'))
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

    with slob.create(outname,
                     compression=args.compression,
                     workdir=args.work_dir,
                     min_bin_size=args.bin_size*1024,
                     observer=observer) as slb:
        begin('content')
        begin('all')
        slb.tag('license.name', args.license_name)
        slb.tag('license.url', args.license_url)
        slb.tag('created.by', args.created_by)
        slb.tag('copyright', '')
        current_dir = os.getcwd()
        os.chdir(os.path.dirname(__file__))
        add_dir(slb, 'js')
        add_dir(slb, 'css')
        add_dir(slb, 'MathJax')
        os.chdir(current_dir)
        CouchArticleSource(args, slb).run()

    p('\nAll done in %s\n' % end('all'))
