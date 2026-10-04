import argparse
import csv
import importlib.metadata
import itertools
import json
import logging
import os
import sys

from . import core
from . import dump
from . import scrape
from . import siteinfo


def cli_siteinfo(args):
    info = siteinfo.get(args.url)
    print(json.dumps(info, indent=2))


CLI_TAGS = ("license.name", "license.url", "created.by", "uri", "created.by")


def get_tags(args, info: siteinfo.Info):

    tags = {
        "license.name": info.license_name,
        "license.url": info.license_url,
        "source": info.server,
        "uri": info.server,
        "label": f"{info.sitename} ({info.sitelang})",
    }

    langlinks = getattr(args, "langlinks", None)
    if langlinks:
        tags["langlinks"] = " ".join(sorted(langlinks))

    for name in CLI_TAGS:
        value = getattr(args, name.replace(".", "_"))
        if value:
            tags[name] = value

    return tags


def get_filters(args):
    filters = []

    filter_dir = args.filter_dir
    if args.filter_file:
        for name in args.filter_file:
            full_name = os.path.expanduser(os.path.join(filter_dir, name))
            print("Reading filters from", full_name)
            with open(full_name) as f:
                for selector in f:
                    selector = selector.strip()
                    if selector:
                        filters.append(selector)

    if args.filter:
        for selector in args.filter:
            filters.append(selector)

    return filters


def run(outname, info, articles, args):
    tags = get_tags(args, info)
    filters = get_filters(args)
    core.create_slob(
        outname,
        info,
        articles,
        content_dirs=args.content_dirs,
        compression=args.compression,
        workdir=args.workdir,
        min_bin_size=args.bin_size,
        no_math=args.no_math,
        html_encoding=args.html_encoding,
        tags=tags,
        filters=filters,
    )


def cli_dump(args):
    outname = dump.get_outname(args)
    siteinfo_dict = dump.get_siteinfo(args)
    info = siteinfo.info(siteinfo_dict, args.local_namespaces)
    dump_files = []
    couch_urls = []
    for name in args.dump_file:
        if name.startswith("http://") or name.startswith("https://"):
            try:
                scrape.mkcouch(name)  # validate url actually points to existing db
            except:
                logging.getLogger(__loader__.name).error(f"Invalid CouchDB URL: {name}")
                raise
            else:
                couch_urls.append(name)
        else:
            dump_files.append(name)
    scrape_articles = [scrape.articles(couch_url, info) for couch_url in couch_urls]
    page_index_path = None
    if dump_files and not args.no_dedupe:
        page_index_path = args.page_index or dump.dump_sidecar_path(
            dump_files, "pages.sqlite"
        )
        dump.build_page_index(dump_files, page_index_path)
    dump_articles = dump.articles(
        dump_files,
        info,
        start_line_spec=args.start_line,
        end_line_spec=args.end_line,
        html_encoding=args.html_encoding,
        remove_embedded_bg=args.remove_embedded_bg,
        ensure_ext_image_urls=args.ensure_ext_image_urls,
        page_index_path=page_index_path,
    )
    run(outname, info, itertools.chain(*scrape_articles, dump_articles), args)


def cli_dump_records_build(args):
    path = args.output or dump.dump_sidecar_path(args.dump_file, "records.sqlite")
    dump.build_records(args.dump_file, path)


def print_table(columns, rows):
    """Print rows as a table: columns padded to their widest value, numbers
    right-aligned, missing values left blank."""
    rows = list(rows)
    texts = [list(columns)] + [["" if v is None else str(v) for v in row] for row in rows]
    widths = [max(map(len, column)) for column in zip(*texts)]
    numeric = [any(isinstance(row[i], int) for row in rows) for i in range(len(columns))]
    for row in texts:
        cells = (
            text.rjust(width) if is_number else text.ljust(width)
            for text, width, is_number in zip(row, widths, numeric)
        )
        print("  ".join(cells).rstrip())


def cli_dump_records_duplicates(args):
    rows = dump.duplicate_records(args.records)
    try:
        if args.csv:
            writer = csv.writer(sys.stdout, lineterminator="\n")
            writer.writerow(dump.DUPLICATES_COLUMNS)
            writer.writerows(rows)
        else:
            print_table(dump.DUPLICATES_COLUMNS, rows)
        sys.stdout.flush()
    except BrokenPipeError:
        # The reader went away (e.g. `less` quit early): stop quietly. Point
        # stdout at devnull so the interpreter's own flush at exit doesn't
        # raise again (see "Note on SIGPIPE" in the signal module docs).
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)


def cli_dump_records_stats(args):
    st = dump.records_stats(args.records)

    def section(title, items):
        print(title)
        texts = [f"{v:,}" if isinstance(v, int) else v for _, v in items]
        label_width = max(len(label) for label, _ in items)
        number_width = max(
            (len(t) for (_, v), t in zip(items, texts) if isinstance(v, int)),
            default=0,
        )
        for (label, value), text in zip(items, texts):
            if isinstance(value, int):
                text = text.rjust(number_width)
            print(f"  {label:<{label_width}}  {text}")
        print()

    section(
        "Records",
        [
            ("dump files", st["files"]),
            ("records", st["records"]),
            ("pages", st["pages"]),
            ("pages with more than one record", st["pages_with_duplicates"]),
            ("extra records (skipped when converting)", st["extra_records"]),
            ("  older revisions", st["older_revisions"]),
            ("  repeats of the newest revision", st["repeats_of_newest"]),
            ("renamed pages (more than one title)", st["renamed_pages"]),
            ("titles used by more than one page", st["shared_titles"]),
        ],
    )
    if st["records_per_page"]:
        section(
            "Pages with more than one record, by number of records",
            [(f"{n} records", pages) for n, pages in st["records_per_page"]],
        )
        section(
            "Most records per page",
            [
                (f"{n} records", f"{title} (page {page_id})")
                for n, page_id, title in st["most_records"]
            ],
        )
    section(
        "Records per dump file",
        [
            (name, f"{records:>9,} records, {int(older):>7,} older revisions")
            for name, records, older in st["per_file"]
        ],
    )
    oldest, newest = st["modified"]
    items = [("all records", f"{oldest} .. {newest}")]
    if st["records_per_page"]:
        dup_oldest, dup_newest = st["duplicates_modified"]
        items.append(("extra records", f"{dup_oldest} .. {dup_newest}"))
    section("Revision timestamps", items)


def cli_scrape(args):
    outname = scrape.get_outname(args)
    siteinfo_dict = scrape.get_siteinfo(args)
    info = siteinfo.info(siteinfo_dict, args.local_namespaces)
    articles = scrape.articles(
        args.couch_url,
        info,
        startkey=args.startkey,
        endkey=args.endkey,
        key=args.key,
        key_file=args.key_file,
        langlinks=args.langlinks,
        html_encoding=args.html_encoding,
        remove_embedded_bg=args.remove_embedded_bg,
        ensure_ext_image_urls=args.ensure_ext_image_urls,
    )
    run(outname, info, articles, args)


def default_filter_dir():
    return os.path.join(os.path.dirname(__file__), "filters")


def arg_parser():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {importlib.metadata.version('mw2slob')}",
    )

    subparsers = arg_parser.add_subparsers()

    parser_siteinfo = subparsers.add_parser(
        "siteinfo", help="Get Mediawiki site metadata"
    )
    parser_siteinfo.add_argument("url")
    parser_siteinfo.add_argument("--api-path", default="/w/api.php")
    parser_siteinfo.set_defaults(func=cli_siteinfo)

    base_parser = argparse.ArgumentParser(add_help=False)

    base_parser.add_argument(
        "-o", "--output-file", type=str, help="Name of output slob file"
    )

    base_parser.add_argument(
        "-c",
        "--compression",
        choices=["lzma2", "zlib"],
        default=core.Defaults.compression,
        help="Name of compression to use. Default: %(default)s",
    )

    base_parser.add_argument(
        "-b",
        "--bin-size",
        type=int,
        default=core.Defaults.min_bin_size,
        help=("Minimum storage bin size in kilobytes. " "Default: %(default)s"),
    )

    base_parser.add_argument(
        "-u",
        "--uri",
        type=str,
        default="",
        help=(
            "Value for uri tag. Slob-specific "
            "article URLs such as bookmarks can be "
            "migrated to another slob based on "
            'matching "uri" tag values'
        ),
    )

    base_parser.add_argument(
        "-l",
        "--license-name",
        type=str,
        default="",
        help=(
            "Value for license.name tag. "
            "This should be name under which "
            "the license is commonly known."
        ),
    )

    base_parser.add_argument(
        "-L",
        "--license-url",
        type=str,
        default="",
        help=("Value for license.url tag. " "This should be a URL for license text"),
    )

    base_parser.add_argument(
        "-a",
        "--created-by",
        type=str,
        default="",
        help=(
            "Value for created.by tag. "
            "Identifier (e.g. name or email) "
            "for slob file creator"
        ),
    )

    base_parser.add_argument(
        "-w",
        "--workdir",
        type=str,
        default=".",
        help=(
            "Directory for temporary files "
            "created during compilation. "
            "Default: %(default)s"
        ),
    )

    base_parser.add_argument(
        "--filter-dir",
        type=str,
        default=default_filter_dir(),
        help=(
            "Directory where filter files "
            "are located. "
            "Default: filters directory in this package"
        ),
    )

    base_parser.add_argument(
        "-f",
        "--filter-file",
        nargs="+",
        help=(
            "Name of filter file. Filter file consists of "
            "CSS selectors (see cssselect documentation "
            "for description of supported selectors), "
            "one selector per line. "
        ),
    )

    base_parser.add_argument(
        "-F",
        "--filter",
        nargs="+",
        help=(
            "CSS selectors for elements to exclude "
            "(see cssselect documentation "
            "for description of supported selectors)"
        ),
    )

    base_parser.add_argument(
        "--html-encoding",
        type=str,
        default="utf-8",
        help=("HTML text encoding. " "Default: %(default)s"),
    )

    base_parser.add_argument(
        "--remove-embedded-bg",
        type=str,
        default="",
        help=(
            "Comma separated list of CSS selectors. "
            "Background will be removed from matching "
            "element's style attribute. For example, to "
            "remove background from all elements with style attribute"
            "specify selector [style]. "
            "Default: %(default)s"
        ),
    )

    base_parser.add_argument(
        "--content-dir",
        dest="content_dirs",
        nargs="+",
        help=("Add content from directory, using full path as key"),
    )

    base_parser.add_argument(
        "--local-namespace",
        dest="local_namespaces",
        nargs="+",
        help=(
            "Treat specified Mediawiki namespaces as local (do not convert to external links)"
        ),
    )

    base_parser.add_argument(
        "--ensure-ext-image-urls",
        action="store_true",
        help=("Convert internal image URLs to external URLs"),
    )

    base_parser.add_argument(
        "--no-math",
        action="store_true",
        help=(
            "Do not include MathJax resources into dictionary "
            "(articles do not use math markup)"
        ),
    )

    parser_dump = subparsers.add_parser(
        "dump", parents=[base_parser], help="Convert HTML dump"
    )

    parser_dump.add_argument(
        "dump_file", nargs="+", type=str, help="Process data from dump file"
    )

    parser_dump.add_argument(
        "--siteinfo",
        type=str,
        help=(
            "Path to Mediawiki siteinfo JSON file. "
            "By default same as dump file name with .siteinfo.json exention"
        ),
    )

    parser_dump.add_argument(
        "-s",
        "--start-line",
        type=str,
        default="1:1",
        help="Start spec: start processing dump at this file:line",
    )

    parser_dump.add_argument(
        "-e",
        "--end-line",
        type=str,
        default=None,
        help="End spec: processing dump at this file:line",
    )

    parser_dump.add_argument(
        "--page-index",
        type=str,
        help=(
            "Path to the page index: a SQLite file recording each page's newest "
            "revision, used to convert only that one when a dump contains a page "
            "several times. Built by a first pass over all dump files if missing "
            "or built from other dump files, and reused otherwise. "
            "By default next to the first dump file, named after it without "
            "the _chunk_N suffix and with .pages.sqlite extension"
        ),
    )

    parser_dump.add_argument(
        "--no-dedupe",
        action="store_true",
        help=(
            "Convert every record, including older revisions of pages the dump "
            "contains more than once (skips the page index)"
        ),
    )

    parser_dump.set_defaults(func=cli_dump)

    parser_dump_records = subparsers.add_parser(
        "dump-records",
        help=(
            "Store every record of an HTML dump in a SQLite file, and report "
            "on pages the dump contains more than once"
        ),
    )
    dump_records_subparsers = parser_dump_records.add_subparsers(required=True)

    parser_dump_records_build = dump_records_subparsers.add_parser(
        "build",
        help=(
            "Write every record of an HTML dump (page id, revision, timestamp, "
            "size, tags, title, location) to a SQLite file"
        ),
    )

    parser_dump_records_build.add_argument(
        "dump_file", nargs="+", type=str, help="Dump file(s) to read"
    )

    parser_dump_records_build.add_argument(
        "-o",
        "--output",
        type=str,
        help=(
            "Path of the SQLite file to write (replaced if it exists). "
            "By default next to the first dump file, named after it without "
            "the _chunk_N suffix and with .records.sqlite extension"
        ),
    )

    parser_dump_records_build.set_defaults(func=cli_dump_records_build)

    parser_dump_records_duplicates = dump_records_subparsers.add_parser(
        "duplicates",
        help=(
            "Print every record of each page that has more than one, grouped "
            "by page, as a table (or CSV with --csv). newest? is yes for the "
            "record conversion keeps, repeat for a later record of that same "
            "revision, empty otherwise"
        ),
    )

    parser_dump_records_duplicates.add_argument(
        "records", type=str, help="Records SQLite file written by dump-records build"
    )

    parser_dump_records_duplicates.add_argument(
        "--csv",
        action="store_true",
        help="Print CSV with a header row instead of a table",
    )

    parser_dump_records_duplicates.set_defaults(func=cli_dump_records_duplicates)

    parser_dump_records_stats = dump_records_subparsers.add_parser(
        "stats",
        help=(
            "Print summary counts: records, pages, pages with more than one "
            "record and their distribution, records per dump file, and the "
            "revision timestamp range"
        ),
    )

    parser_dump_records_stats.add_argument(
        "records", type=str, help="Records SQLite file written by dump-records build"
    )

    parser_dump_records_stats.set_defaults(func=cli_dump_records_stats)

    parser_scrape = subparsers.add_parser(
        "scrape", parents=[base_parser], help="Convert from mwscrape CouchDB"
    )

    parser_scrape.add_argument(
        "couch_url",
        type=str,
        help="URL of CouchDB created by mwscrape to be used as input",
    )

    parser_scrape.add_argument(
        "-s", "--startkey", help="Skip articles with titles before this one when sorted"
    )

    parser_scrape.add_argument(
        "-e", "--endkey", help="Stop processing when this title is reached"
    )

    parser_scrape.add_argument(
        "-k", "--key", nargs="+", help="Process specified keys only"
    )

    parser_scrape.add_argument(
        "-K", "--key-file", help="Process only keys specified in file"
    )

    parser_scrape.add_argument(
        "-ll",
        "--langlinks",
        default=None,
        nargs="+",
        help=(
            "Include article titles from Wikipedia "
            "language links for these languages if available"
        ),
    )

    parser_scrape.set_defaults(func=cli_scrape)

    return arg_parser


def main():
    logging.basicConfig()
    parser = arg_parser()
    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "main":
    main()
