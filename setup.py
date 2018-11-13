from setuptools import find_packages, setup
from ultron import __version__, __author__

setup(
    name='ultron',
    version=__version__,
    author=__author__,
    url='http://github.com/orga/Ultron',
    description='Process-enforcement bot',
    package_dir={'ultron': 'ultron'},
    packages=find_packages(),
    scripts=[
        'ultron/index.py',
    ],
    install_requires=[
        'py-gfm',
        'requests',
        'grequests',
        'watchdog',
    ]
)
