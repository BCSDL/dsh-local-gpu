import importlib.util, pathlib, unittest, sys, subprocess, os
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]/'backend'))
spec=importlib.util.spec_from_file_location('bridge',pathlib.Path(__file__).parents[1]/'backend/bridge.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class Tests(unittest.TestCase):
 @unittest.skipUnless(os.name=='nt','Windows job object')
 def test_owned_child_exits_when_job_closes(self):
  child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
  try:job=module.Job(child.pid);job.close();child.wait(timeout=5)
  finally:
   if child.poll() is None:child.kill();child.wait()
 def test_rejects_arbitrary_nodes_and_large_allocations(self):
  r=module.Runtime(pathlib.Path.cwd(),8198)
  for prompt in ({'1':{'class_type':'ArbitraryPython','inputs':{}}},{'1':{'class_type':'EmptyFlux2LatentImage','inputs':{'width':4096,'height':4096,'batch_size':1}}}):
   with self.assertRaises(ValueError):r.validate(prompt)
 def test_save_prefix_cannot_escape_output(self):
  r=module.Runtime(pathlib.Path.cwd(),8198);q={'1':{'class_type':'SaveImage','inputs':{'filename_prefix':'../../outside'}}};self.assertEqual(r.validate(q)['1']['inputs']['filename_prefix'],'DSH')
if __name__=='__main__':unittest.main()
