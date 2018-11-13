from setuptools import setup

setup(
    classifiers=[
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
    install_requires=['grequests>=0.3,<0.4',
                      'requests>=2.11,<2.12',
                      'watchdog>=0.8,<0.9'],
)
