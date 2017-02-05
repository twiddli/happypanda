import argparse

parser = argparse.ArgumentParser(prog='Happypanda',
                                description='A manga/doujinshi manager with tagging support')
parser.add_argument('-d', '--debug', action='store_true',
                    help='happypanda_debug_log.log will be created in main directory')
parser.add_argument('-v', '--version', action='version',
                    version='Happypanda v{}'.format("1.0"))
parser.add_argument('-e', '--exceptions', action='store_true',
                    help='Disable custom excepthook')
parser.add_argument('-x', '--dev', action='store_true',
                    help='Development Switch')
parser.add_argument('-p', '--home', action='store_true',
                    help="Create files at ~")

args = parser.parse_args()
