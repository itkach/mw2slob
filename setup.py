import os
from distutils.core import setup

PACKAGE_NAME = 'mwscrape2slob'

def find_package_data():
    cwd = os.getcwd()
    os.chdir(PACKAGE_NAME)
    results = []
    for name in ['css', 'js', 'filters', 'MathJax']:
        for root, _dirs, files in os.walk(name):
            for filename in files:
                results.append(os.path.join(root, filename))
    os.chdir(cwd)
    return results

setup(name=PACKAGE_NAME,
      version='1.0',
      description='Converts MediaWiki content from mwscrape CouchDB to slob',
      author='Igor Tkach',
      author_email='itkach@gmail.com',
      url='http://github.com/itkach/mwscrape2slob',
      license='GPL3',
      packages=[PACKAGE_NAME],
      package_data={PACKAGE_NAME: find_package_data()},
      install_requires=['Slob >= 1.0', 'lxml', 'CouchDB',
                        'cssselect', 'cssutils'],
      zip_safe=False,
      entry_points={'console_scripts': ['{0}={0}:main'.format(PACKAGE_NAME)]})
