import argparse
import json
import logging
import os

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
    articles = dump.articles(args, info)
    run(outname, info, articles, args)


def cli_scrape(args):
    outname = scrape.get_outname(args)
    siteinfo_dict = scrape.get_siteinfo(args)
    info = siteinfo.info(siteinfo_dict, args.local_namespaces)
    articles = scrape.articles(args, info)
    run(outname, info, articles, args)


def default_filter_dir():
    return os.path.join(os.path.dirname(__file__), "filters")


def arg_parser():
    arg_parser = argparse.ArgumentParser()

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

    parser_dump.set_defaults(func=cli_dump)

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
