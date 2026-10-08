"""ComfyUI-compatible loopback bridge with one GPU-only child per image job."""
import argparse, asyncio, json, os, pathlib, subprocess, sys, time, uuid
from aiohttp import web, ClientSession, ClientTimeout
from PIL import Image
from windows_job import Job

APP='dsh-local-gpu'
ALLOWED={'UNETLoader','CLIPLoader','VAELoader','CLIPTextEncode','ConditioningZeroOut','FluxGuidance','CFGGuider','BasicGuider','RandomNoise','KSamplerSelect','Flux2Scheduler','EmptyFlux2LatentImage','SamplerCustomAdvanced','VAEDecode','SaveImage','LoadImage','VAEEncode','ReferenceLatent','ImageScaleToTotalPixels'}
class Runtime:
 def __init__(self,comfy,port):
  self.comfy=pathlib.Path(comfy).resolve();self.port=port;self.child=None;self.job=None;self.busy=False
  self.data=pathlib.Path.home()/'.local-ai-tools'/'local-images';self.data.mkdir(parents=True,exist_ok=True)
  self.input=self.data/'input';self.output=self.data/'output';self.history=self.data/'history'
  for folder in (self.input,self.output,self.history):folder.mkdir(exist_ok=True)
 def validate(self,prompt):
  if not isinstance(prompt,dict) or not 1<=len(prompt)<=30:raise ValueError('Invalid workflow')
  for node in prompt.values():
   kind=node.get('class_type');values=node.get('inputs',{})
   if kind not in ALLOWED:raise ValueError('Unsupported workflow node: '+str(kind))
   for key in ('width','height'):
    if key in values and (not isinstance(values[key],int) or values[key]<256 or values[key]>1024 or values[key]%16):raise ValueError('Dimensions must be 256–1024, multiples of 16')
   if kind=='EmptyFlux2LatentImage' and values.get('batch_size')!=1:raise ValueError('Only one image per job')
   if kind=='Flux2Scheduler' and values.get('steps')!=4:raise ValueError('Distilled workflow requires four steps')
   if kind=='UNETLoader' and values.get('unet_name')!='flux-2-klein-4b-fp8.safetensors':raise ValueError('Only pinned FLUX klein 4B FP8 is configured')
   if kind=='CLIPLoader' and (values.get('clip_name')!='qwen_3_4b.safetensors' or values.get('device','default')!='default'):raise ValueError('Unsupported encoder/device')
   if kind=='VAELoader' and values.get('vae_name')!='flux2-vae.safetensors':raise ValueError('Unsupported VAE')
   if kind=='LoadImage':
    path=self.input/str(values.get('image',''))
    if path.parent.resolve()!=self.input.resolve() or not path.is_file():raise ValueError('Reference must be an uploaded image')
   if kind=='SaveImage':values['filename_prefix']='DSH'
  return prompt
 def active_classroom(self):
  homes=[pathlib.Path.home()/'.dsh/classroom',pathlib.Path.home()/'.codex-local/classroom']
  if os.environ.get('DSH_HOME'):homes.append(pathlib.Path(os.environ['DSH_HOME'])/'classroom')
  for home in homes:
   for path in (home/'jobs').glob('*/job.json'):
    try:
     if json.loads(path.read_text(encoding='utf-8')).get('state') in ('recording','queued','running','processing'):return True
    except (OSError,ValueError):continue
  return False
 async def prepare_gpu(self,session):
  if self.active_classroom():raise RuntimeError('请先结束课堂录音/分析，再进行生图。')
  async with session.get('http://127.0.0.1:11434/api/ps') as response:loaded=(await response.json()).get('models',[])
  if any(m.get('name')!='gemma4:12b-it-qat' for m in loaded):raise RuntimeError('Another Ollama model is loaded; it will not be unloaded automatically')
  if loaded:
   async with session.post('http://127.0.0.1:11434/api/generate',json={'model':'gemma4:12b-it-qat','keep_alive':0,'stream':False}) as response:
    if response.status!=200:raise RuntimeError('Cannot release Gemma for image generation')
  process=await asyncio.create_subprocess_exec('nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
  stdout,_=await process.communicate()
  if process.returncode or int(stdout.decode().splitlines()[0])<12000:raise RuntimeError('Not enough free GPU memory (requires 12000 MiB); no RAM offload is used')
 async def stop_child(self):
  if self.child and self.child.returncode is None:
   self.child.terminate()
   try:await asyncio.wait_for(self.child.wait(),10)
   except asyncio.TimeoutError:self.child.kill();await self.child.wait()
  self.child=None
  if self.job:self.job.close();self.job=None
 async def run(self,ident,prompt):
  result=None
  try:
   async with ClientSession(timeout=ClientTimeout(total=1200)) as session:
    await self.prepare_gpu(session)
    # Reject an unrelated listener; this bridge owns only its own child.
    try:
     reader,writer=await asyncio.open_connection('127.0.0.1',self.port+1);writer.close();await writer.wait_closed();raise RuntimeError('Internal inference port is occupied; no process was stopped')
    except ConnectionRefusedError:pass
    args=[sys.executable,str(self.comfy/'main.py'),'--listen','127.0.0.1','--port',str(self.port+1),'--gpu-only','--fp8_e4m3fn-text-enc','--disable-async-offload','--disable-pinned-memory','--cache-none','--disable-all-custom-nodes','--offline','--input-directory',str(self.input),'--output-directory',str(self.output)]
    with (self.data/'inference.log').open('wb') as log:
     self.child=await asyncio.create_subprocess_exec(*args,cwd=str(self.comfy),stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
     self.job=Job(self.child.pid)
     base=f'http://127.0.0.1:{self.port+1}'
     for _ in range(180):
      if self.child.returncode is not None:raise RuntimeError('ComfyUI startup failed; see local-images/inference.log')
      try:
       async with session.get(base+'/system_stats') as r:
        if r.status==200:break
      except Exception:pass
      await asyncio.sleep(.5)
     else:raise RuntimeError('ComfyUI startup timed out')
     async with session.post(base+'/prompt',json={'prompt':prompt}) as r:
      body=await r.json()
      if r.status!=200:raise RuntimeError('Workflow rejected: '+json.dumps(body)[:1500])
     upstream_id=body['prompt_id']
     deadline=time.monotonic()+1100
     while time.monotonic()<deadline:
      async with session.get(base+'/history/'+upstream_id) as r:result=(await r.json()).get(upstream_id)
      if result and result.get('status',{}).get('completed'):break
      if self.child.returncode is not None:raise RuntimeError('Image inference process exited')
      await asyncio.sleep(.5)
     else:raise RuntimeError('Image inference timed out')
  except Exception as error:result={'outputs':{},'status':{'completed':True,'status_str':'error','messages':[['execution_error',{'exception_message':str(error)}]]}}
  finally:
   await self.stop_child()  # GPU weights are freed, not retained/offloaded in RAM.
   (self.history/(ident+'.json')).write_text(json.dumps(result),encoding='utf-8')
   self.busy=False
 async def prompt(self,request):
  if self.busy:raise web.HTTPConflict(text='Another local image job is running')
  try:prompt=self.validate((await request.json())['prompt'])
  except (ValueError,KeyError,TypeError) as err:raise web.HTTPBadRequest(text=str(err))
  self.busy=True;ident=uuid.uuid4().hex;asyncio.create_task(self.run(ident,prompt));return web.json_response({'prompt_id':ident,'number':0,'node_errors':{}})
 async def upload(self,request):
  reader=await request.multipart();part=await reader.next()
  while part and part.name!='image':part=await reader.next()
  if part is None:raise web.HTTPBadRequest(text='Missing image')
  data=bytearray()
  while chunk:=await part.read_chunk():
   data.extend(chunk)
   if len(data)>20*1024*1024:raise web.HTTPRequestEntityTooLarge(max_size=20*1024*1024,actual_size=len(data))
  import io
  try:
   image=Image.open(io.BytesIO(data));image.load()
   if image.width*image.height>16_000_000:raise ValueError('Reference exceeds 16 megapixels')
   name=uuid.uuid4().hex+'.png';image.convert('RGB').save(self.input/name)
  except Exception as err:raise web.HTTPBadRequest(text='Invalid image: '+str(err))
  return web.json_response({'name':name,'subfolder':'','type':'input'})
 async def get_history(self,request):
  ident=request.match_info['id']
  if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise web.HTTPBadRequest()
  path=self.history/(ident+'.json');return web.json_response({ident:json.loads(path.read_text())} if path.exists() else {})
 async def view(self,request):
  if request.query.get('subfolder','')!='':raise web.HTTPBadRequest()
  name=request.query.get('filename','');path=self.output/name
  if path.parent.resolve()!=self.output.resolve() or not path.is_file():raise web.HTTPNotFound()
  return web.FileResponse(path)
 async def health(self,request):return web.json_response({'app':APP,'ready':True,'busy':self.busy,'model':'FLUX.2-klein-4B-FP8','inference':'GPU only; one child per job'})
 async def stats(self,request):return web.json_response({'system':{'os':os.name},'devices':[]})
 async def cleanup(self,app):await self.stop_child()
 def app(self):
  @web.middleware
  async def local_origin(request,handler):
   if request.headers.get('Origin') not in (None,f'http://127.0.0.1:{self.port}',f'http://localhost:{self.port}'):raise web.HTTPForbidden()
   return await handler(request)
  app=web.Application(client_max_size=32*1024*1024,middlewares=[local_origin]);app.add_routes([web.get('/health',self.health),web.get('/system_stats',self.stats),web.post('/prompt',self.prompt),web.post('/upload/image',self.upload),web.get('/history/{id}',self.get_history),web.get('/view',self.view)]);app.on_cleanup.append(self.cleanup);return app
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8188);parser.add_argument('--comfy',default=str(pathlib.Path.home()/'.local-ai-tools/comfyui/ComfyUI-0.39.0'));args=parser.parse_args();web.run_app(Runtime(args.comfy,args.port).app(),host='127.0.0.1',port=args.port,print=None)
