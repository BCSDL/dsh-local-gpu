"""Kill an owned inference child if its bridge process exits on Windows."""
import ctypes, os
from ctypes import wintypes as w
class Job:
 def __init__(self,pid):
  self.handle=None
  if os.name!='nt':return
  class IO(ctypes.Structure):_fields_=[(x,ctypes.c_uint64) for x in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
  class Basic(ctypes.Structure):_fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',w.DWORD),('min_working',ctypes.c_size_t),('max_working',ctypes.c_size_t),('active_limit',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
  class Limits(ctypes.Structure):_fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
  k=ctypes.WinDLL('kernel32',use_last_error=True);self.kernel=k
  k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];k.CreateJobObjectW.restype=w.HANDLE
  k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD];k.SetInformationJobObject.restype=w.BOOL
  k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
  k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];k.AssignProcessToJobObject.restype=w.BOOL
  k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
  self.handle=k.CreateJobObjectW(None,None);limits=Limits();limits.basic.flags=0x2000
  if not self.handle or not k.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):self.close();raise ctypes.WinError(ctypes.get_last_error())
  process=k.OpenProcess(0x100|0x1,False,pid)
  try:
   if not process or not k.AssignProcessToJobObject(self.handle,process):self.close();raise ctypes.WinError(ctypes.get_last_error())
  finally:
   if process:k.CloseHandle(process)
 def close(self):
  if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None
