"""The same local image runtime for Codex CLI via stdio MCP."""
import base64,json,os,pathlib,random,subprocess,sys,threading,time,urllib.request,uuid
BASE='http://127.0.0.1:8188';CHILD=None;LOCK=threading.Lock();START_LOCK=threading.Lock()
ROOT=pathlib.Path(__file__).parents[1]
def request(path,data=None):
 raw=None if data is None else json.dumps(data).encode();req=urllib.request.Request(BASE+path,data=raw,headers={'Content-Type':'application/json'});return json.load(urllib.request.urlopen(req,timeout=120))
def ready():
 global CHILD
 try:
  if request('/health').get('app')=='dsh-local-gpu':return
 except Exception:pass
 CHILD=subprocess.Popen([sys.executable,str(ROOT/'backend/bridge.py')],stdout=subprocess.DEVNULL,stderr=sys.stderr,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
 for _ in range(50):
  try:
   if request('/health').get('app')=='dsh-local-gpu':return
  except Exception:pass
  if CHILD.poll() is not None:raise RuntimeError('Local image runtime failed to start, or port 8188 belongs to another app')
  time.sleep(.2)
 raise RuntimeError('Local image runtime did not become ready')
def generate(args):
 if not isinstance(args,dict) or not isinstance(args.get('prompt'),str) or not args['prompt'].strip():raise ValueError('A non-empty prompt is required')
 with START_LOCK:ready()
 image=args.get('image_path');name=None
 if image:
  path=pathlib.Path(image)
  if path.stat().st_size>20*1024*1024:raise ValueError('Reference exceeds 20 MiB')
  data=path.read_bytes()
  boundary='dsh-'+uuid.uuid4().hex;payload=(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="reference.png"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+data+f'\r\n--{boundary}--\r\n'.encode());req=urllib.request.Request(BASE+'/upload/image',data=payload,headers={'Content-Type':'multipart/form-data; boundary='+boundary});name=json.load(urllib.request.urlopen(req,timeout=120))['name']
 workflow=json.loads((ROOT/'workflows'/('edit.json' if image else 'generate.json')).read_text());seed=random.randrange(2**32)
 def fill(value):
  if isinstance(value,dict):return {k:fill(v) for k,v in value.items()}
  if isinstance(value,list):return [fill(v) for v in value]
  if value=='{{prompt}}':return args['prompt']
  if value=='{{seed}}':return seed
  if value=='{{image}}':return name
  return value
 ident=request('/prompt',{'prompt':fill(workflow)})['prompt_id']
 for _ in range(1200):
  result=request('/history/'+ident).get(ident)
  if result:
   if result['status']['status_str']=='error':raise RuntimeError(str(result['status']['messages']))
   asset=next(a for output in result['outputs'].values() for a in output.get('images',[]));path=pathlib.Path.home()/'.local-ai-tools/local-images/output'/asset['filename']
   return {'content':[{'type':'text','text':str(path)},{'type':'image','mimeType':'image/png','data':base64.b64encode(path.read_bytes()).decode()}]}
  time.sleep(1)
 raise RuntimeError('Local image job timed out')
TOOLS=[{'name':'generate_local_image','description':'Generate an image, or edit an explicitly supplied image_path, using local FLUX.2 klein 4B. Finish classroom recording/analysis first. Temporarily releases Gemma, uses GPU only, and frees its owned image process before responding.','inputSchema':{'type':'object','properties':{'prompt':{'type':'string'},'image_path':{'type':'string'}},'required':['prompt']},'annotations':{'readOnlyHint':False,'destructiveHint':False,'openWorldHint':False}}]
def send(value):
 with LOCK:print(json.dumps(value),flush=True)
def handle(q):
 ident=q.get('id');method=q.get('method');result=None
 try:
  if method=='initialize':result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'dsh-local-gpu','version':'0.1.2'}}
  elif method=='ping':result={}
  elif method=='tools/list':result={'tools':TOOLS}
  elif method=='resources/list':result={'resources':[]}
  elif method=='resources/templates/list':result={'resourceTemplates':[]}
  elif method=='tools/call':
   if q['params']['name']!='generate_local_image':raise ValueError('Unknown tool')
   result=generate(q['params'].get('arguments',{}))
  elif ident is not None:send({'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Unsupported method'}});return
  if ident is not None:send({'jsonrpc':'2.0','id':ident,'result':result})
 except Exception as err:
  if ident is not None:send({'jsonrpc':'2.0','id':ident,'result':{'content':[{'type':'text','text':str(err)}],'isError':True}})
if __name__=='__main__':
 try:
  for line in sys.stdin:
   try:q=json.loads(line)
   except ValueError:send({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Invalid JSON'}});continue
   if q.get('method')=='tools/call':threading.Thread(target=handle,args=(q,),daemon=True).start()
   else:handle(q)
 finally:
  if CHILD and CHILD.poll() is None:CHILD.terminate();CHILD.wait(timeout=10)
