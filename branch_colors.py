"""Stable, restrained remote colors derived from ref identity, not short names."""
import hashlib
from PySide6.QtGui import QColor


def remote_name(repo, branch):
    ref = repo.branch_refs.get(branch, 'refs/heads/'+branch)
    if not ref.startswith('refs/remotes/'):
        return None
    suffix = ref.removeprefix('refs/remotes/')
    for name in sorted(repo.remote_names, key=len, reverse=True):
        if suffix.startswith(name+'/'):
            return name
    return suffix.split('/', 1)[0]


def remote_color(name):
    digest = hashlib.sha256(name.encode('utf-8')).digest()
    # One quiet green/teal family, with small changes in hue and brightness.
    return QColor.fromHslF(.40+.16*digest[3]/255, .30+.10*digest[4]/255, .58+.12*digest[5]/255)
