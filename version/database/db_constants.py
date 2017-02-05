#"""
#This file is part of Happypanda.
#Happypanda is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 2 of the License, or
#any later version.
#Happypanda is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#You should have received a copy of the GNU General Public License
#along with Happypanda.  If not, see <http://www.gnu.org/licenses/>.
#"""

import os

from .args import args

CONTENT_DIR = os.path.dirname(os.path.realpath(__file__)) if os.name == 'posix' else os.getcwd()
if args.home:
    CONTENT_DIR = os.path.expanduser('~/HappypandaBin')

DB_NAME = 'happypanda.db'
THUMB_NAME = "thumbnails"
DB_ROOT = os.path.join(CONTENT_DIR, '../db' if not args.home and os.name == 'posix' else 'db')
THUMBNAIL_PATH = os.path.join(DB_ROOT, THUMB_NAME)
DB_PATH = os.path.join(DB_ROOT, DB_NAME)

DB_VERSION = [0.26] # a list of accepted db versions. E.g. v3.5 will be backward compatible with v3.1 etc.
CURRENT_DB_VERSION = DB_VERSION[0]
REAL_DB_VERSION = DB_VERSION[len(DB_VERSION)-1]
METHOD_QUEUE = None
METHOD_RETURN = None
DATABASE = None

class NoDatabaseConnection(Exception): pass
