from codecs import open
from os import path, name
from sys import maxsize

from setuptools import setup, find_packages

here = path.abspath(path.dirname(__file__))

install_requires = [
    'requests',
    'beautifulsoup4',
    'scandir',
    'rarfile',
    'watchdog',
    'robobrowser',
    'Send2Trash',
    'pillow',
    'python-dateutil',
    'QtAwesome',
    'appdirs'
]

if name != "posix" and maxsize > 2**32 is False:
    install_requires.append('pyqt5')

setup(
    name='Happypanda',
    version='1.0',
    description='A cross platform manga/doujinshi manager with namespace & tag support',
    long_description=open('README.rst').read(),
    url='https://github.com/Pewpews/happypanda',
    author='Pewpew',
    author_email='pew@pewpew.moe',
    license='GPLv2+',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: End Users/Desktop',
        'Topic :: Database :: Front-Ends',
        'License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
    ],
    keywords=['manga', 'doujinshi', 'downloader', 'management', 'cross-platform'],
    packages=find_packages(exclude=['tests', 'misc']),
    include_package_data=True,
    package_data={
        '': ['res/*'],
        'res': ['*'],
    },
    install_requires=install_requires,
    entry_points={
        'gui_scripts': [
            'happypanda=happypanda.__main__:main',
        ],
    },
)
