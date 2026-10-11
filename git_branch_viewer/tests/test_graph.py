import os
import subprocess
import tempfile
import unittest
from git_reader import read_repository
from graph import build_graph, terminal_tips
from layout import layout

class GitGraphTest(unittest.TestCase):
    def test_real_git_merges_aliases_and_expansion(self):
        with tempfile.TemporaryDirectory() as path:
            def git(*args):
                return subprocess.check_output(['git','-C',path,*args],text=True,stderr=subprocess.DEVNULL).strip()
            git('init','-b','main')
            git('config','user.name','Tester')
            git('config','user.email','tester@example.invalid')
            def commit(message):
                git('commit','--allow-empty','-m',message)
                return git('rev-parse','HEAD')
            root=commit('Root')
            git('branch','old')
            commit('Linear one'); commit('Linear two')
            fork=commit('Fork')
            git('checkout','-b','experiment')
            commit('Experiment one'); a=commit('Experiment two\n\nDetails')
            git('branch','alias')
            git('checkout','main')
            commit('Main one')
            git('checkout','-b','side')
            side=commit('Side')
            git('checkout','main')
            commit('Main two')
            git('merge','--no-ff','side','-m','Merge side')
            b=git('rev-parse','HEAD')
            repo=read_repository(path)
            self.assertEqual(set(terminal_tips(repo)),{a,b})
            self.assertEqual(set(repo.branches[a]),{'alias','experiment'})
            self.assertEqual(len(repo.commits[b].parents),2)
            self.assertIn('Details',repo.commits[a].message)
            graph=build_graph(repo)
            positions=layout(graph)
            self.assertTrue(all(positions[t][1]==0 for t in graph.tips))
            for e in graph.edges:
                self.assertGreater(positions[e.parent][1],positions[e.child][1])
                chain=(e.child,*e.hidden,e.parent)
                for child,parent in zip(chain,chain[1:]):
                    self.assertIn(parent,repo.commits[child].parents)
            hidden={o for e in graph.edges for o in e.hidden}
            self.assertEqual(graph.nodes|hidden,set(repo.commits))
            self.assertIn(root,graph.nodes)
            self.assertIn(fork,graph.nodes)
            expanded=build_graph(repo,hidden)
            self.assertFalse(any(e.hidden for e in expanded.edges))
            # Offscreen GUI smoke test, including selection and redraw.
            from PySide6.QtWidgets import QApplication
            from viewer import Window
            app=QApplication.instance() or QApplication([])
            window=Window(path)
            window.show(); app.processEvents()
            self.assertEqual(len(window.repo.commits),len(repo.commits))
            window.expanded.update(hidden); window.render(); window.view.fit()
            node=next(i for i in window.scene.items() if hasattr(i,'oid'))
            node.setSelected(True); app.processEvents()
            self.assertIn(node.oid,window.details.toPlainText())
            window.collapse(); window.refresh(); window.close()
    def test_empty_repo(self):
        with tempfile.TemporaryDirectory() as path:
            subprocess.run(['git','init',path],check=True,capture_output=True)
            repo=read_repository(path)
            self.assertEqual(build_graph(repo).nodes,set())

if __name__=='__main__':
    unittest.main()
