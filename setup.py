import os
from setuptools import setup

PACKAGE_NAME = "mw2slob"


def find_package_data():
    cwd = os.getcwd()
    os.chdir(PACKAGE_NAME)
    results = []
    for name in ["css", "js", "images", "filters", "MathJax"]:
        for root, _, files in os.walk(name):
            for filename in files:
                results.append(os.path.join(root, filename))
    os.chdir(cwd)
    return results


setup(
    name=PACKAGE_NAME,
    version="1.0",
    description=(
        "Create slob dictionary files from mwscrape CouchDB "
        "or Wikimedia Enterprise HTML Dumps"
    ),
    author="Igor Tkach",
    author_email="itkach@gmail.com",
    url="http://github.com/itkach/mw2slob",
    license="GPL3",
    packages=[PACKAGE_NAME],
    package_data={PACKAGE_NAME: find_package_data()},
    install_requires=["Slob >= 1.0", "lxml", "CouchDB", "cssselect", "cssutils", "bs4"],
    zip_safe=False,
    entry_points={
        "console_scripts": [
            f"mw2slob={PACKAGE_NAME}.cli:main",
        ]
    },
)
