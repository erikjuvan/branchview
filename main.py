import argparse
import sys
from PySide6.QtWidgets import QApplication
from viewer import Window

def main():
    parser = argparse.ArgumentParser(description='Read-only terminal-branch Git graph')
    parser.add_argument('repository', nargs='?', help='Local repository directory')
    parser.add_argument('--branches-only', action='store_true',
                        help='Show branch tips without loading ancestor history')
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    window = Window(args.repository, branches_only=args.branches_only)
    window.show()
    return app.exec()

if __name__ == '__main__':
    raise SystemExit(main())
