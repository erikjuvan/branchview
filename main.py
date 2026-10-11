import argparse
import sys
from PySide6.QtWidgets import QApplication
from viewer import Window

def main():
    parser = argparse.ArgumentParser(description='Read-only terminal-branch Git graph')
    parser.add_argument('repository', nargs='?', help='Local repository directory')
    parser.add_argument('--branches-only', action='store_true',
                        help='Show branch tips without loading ancestor history')
    parser.add_argument('--max-commits', type=int, default=500,
                        help='History commit budget (default: 500; 0 for all history)')
    args = parser.parse_args()
    if args.max_commits < 0:
        parser.error('--max-commits must be non-negative')
    app = QApplication(sys.argv[:1])
    window = Window(args.repository, branches_only=args.branches_only, history_limit=args.max_commits or None)
    window.show()
    return app.exec()

if __name__ == '__main__':
    raise SystemExit(main())
